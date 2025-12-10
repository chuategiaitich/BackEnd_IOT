from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any
import os
import httpx
import uvicorn
from dotenv import load_dotenv

load_dotenv()
app = FastAPI(title="IoT Backend with Supabase")

# Cho phép frontend gọi API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import mqtt_handler (supabase client được init bên trong)
from mqtt_handler import setup_mqtt, publish_to_mqtt, save_to_supabase, supabase

# setup_mqtt()


@app.on_event("startup")
async def startup_event():
    from mqtt_handler import setup_mqtt
    setup_mqtt()          # Chỉ chạy 1 lần khi app khởi động
    print("MQTT đã được khởi tạo trong FastAPI startup event")

class PublishRequest(BaseModel):
    topic: str
    table_name: str  # REQUIRED: messages, values, history, users
    data: Dict[str, Any]  # Dữ liệu thực tế cần lưu

async def get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing token")
    token = authorization.split(" ")[1]
    resp = httpx.get(
        f"{os.getenv('SUPABASE_URL')}/auth/v1/user",
        headers={
            "apikey": os.getenv("SUPABASE_ANON_KEY"),
            "Authorization": f"Bearer {token}"
        }
    )
    if resp.status_code != 200:
        raise HTTPException(401, "Invalid token")
    user = resp.json()

    if supabase:
        check = supabase.table("users").select("id").eq("email", user["email"]).execute()
        if not check.data:
            raise HTTPException(403, "User not registered in system")
    return user

class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

@app.post("/login")
async def login(req: LoginRequest):
    """
    Đăng nhập user và trả về access_token từ Supabase Auth.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            auth_response = await client.post(
                f"{os.getenv('SUPABASE_URL')}/auth/v1/token?grant_type=password",
                headers={
                    "apikey": os.getenv("SUPABASE_ANON_KEY"),
                    "Content-Type": "application/json"
                },
                json={
                    "email": req.email,
                    "password": req.password
                }
            )
        
        if auth_response.status_code != 200:
            error_data = auth_response.json()
            error_msg = error_data.get('msg') or error_data.get('error_description') or error_data.get('message', 'Unknown error')
            raise HTTPException(400, f"Đăng nhập thất bại: {error_msg}")
        
        auth_data = auth_response.json()
        access_token = auth_data.get("access_token")
        user = auth_data.get("user")
        
        if not access_token:
            raise HTTPException(500, "Không lấy được access_token")
        
        return {
            "status": "success",
            "message": "Đăng nhập thành công!",
            "access_token": access_token,
            "user": user
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Lỗi đăng nhập: {str(e)}")


@app.post("/register")
async def register(req: RegisterRequest):
    """
    Đăng ký user mới (Email confirmation đã TẮT):
    1. Tạo user trong Supabase Auth (email + password)
    2. Tự động tạo profile trong table users (name + email)
    """
    try:
        # BƯỚC 1: Đăng ký vào Supabase Auth
        async with httpx.AsyncClient(timeout=30.0) as client:
            auth_response = await client.post(
                f"{os.getenv('SUPABASE_URL')}/auth/v1/signup",
                headers={
                    "apikey": os.getenv("SUPABASE_ANON_KEY"),
                    "Content-Type": "application/json"
                },
                json={
                    "email": req.email,
                    "password": req.password,
                    "data": {
                        "name": req.name  # Lưu name vào user metadata
                    }
                }
            )
        
        if auth_response.status_code != 200:
            error_data = auth_response.json()
            error_msg = error_data.get('msg') or error_data.get('error_description') or error_data.get('message', 'Unknown error')
            raise HTTPException(400, f"Đăng ký Auth thất bại: {error_msg}")
        
        auth_data = auth_response.json()
        
        # Lấy thông tin user từ response
        user_id = auth_data.get("user", {}).get("id")
        user_email = auth_data.get("user", {}).get("email", req.email)
        
        if not user_id:
            raise HTTPException(500, "Không lấy được user_id từ Supabase Auth")
        
        # BƯỚC 2: Tạo profile trong table users
        user_profile = {
            "id": user_id,
            "name": req.name,
            "email": user_email
        }
        
        try:
            profile_result = supabase.table("users").insert(user_profile).execute()
            
            if profile_result.data:
                return {
                    "status": "success",
                    "message": "Đăng ký thành công! Bạn có thể đăng nhập ngay.",
                    "user": {
                        "id": user_id,
                        "name": req.name,
                        "email": user_email
                    }
                }
            else:
                print(f"⚠️ PROFILE INSERT FAILED - NO DATA: {profile_result}")  # Debug thêm
                return {
                    "status": "partial_success",
                    "message": "Auth user đã tạo nhưng profile chưa tạo được. Vui lòng thử lại endpoint /create-profile",
                    "user": {
                        "id": user_id,
                        "name": req.name,
                        "email": user_email
                    }
                }
                
        except Exception as profile_error:
            print(f"⚠️ WARNING: Profile insert failed: {str(profile_error)}")  # Đã có
            return {
                "status": "partial_success",
                "message": "Auth user đã tạo nhưng profile chưa tạo được",
                "user": {
                    "id": user_id,
                    "name": req.name,
                    "email": user_email
                },
                "note": "Vui lòng login và gọi POST /create-profile để tạo profile"
            }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Lỗi đăng ký: {str(e)}")


@app.post("/create-profile")
async def create_profile(user=Depends(get_current_user)):
    """
    Tạo profile trong table users sau khi user đã xác nhận email
    Endpoint này dùng cho trường hợp email confirmation được bật
    """
    try:
        user_id = user.get("id")
        user_email = user.get("email")
        user_name = user.get("user_metadata", {}).get("name", user_email.split("@")[0])
        
        # Kiểm tra xem profile đã tồn tại chưa
        existing = supabase.table("users").select("id").eq("id", user_id).execute()
        
        if existing.data:
            return {
                "status": "already_exists",
                "message": "Profile đã tồn tại",
                "user": existing.data[0]
            }
        
        # Tạo profile mới
        user_profile = {
            "id": user_id,
            "name": user_name,
            "email": user_email
        }
        
        result = supabase.table("users").insert(user_profile).execute()
        
        if result.data:
            return {
                "status": "success",
                "message": "Profile đã được tạo thành công!",
                "user": result.data[0]
            }
        else:
            raise HTTPException(500, "Không thể tạo profile")
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Lỗi tạo profile: {str(e)}")

@app.post("/publish")
async def publish(req: PublishRequest, user=Depends(get_current_user)):
    try:
        # Validate table_name
        valid_tables = ["messages", "values", "history", "users"]
        if req.table_name not in valid_tables:
            raise HTTPException(400, f"table_name phải là một trong: {valid_tables}")

        # Chuẩn bị data để lưu
        data_to_save = req.data.copy()

        # Xử lý theo từng table
        if req.table_name == "messages":
            # Table messages cần: topic, payload, value (optional)
            data_to_save.setdefault("topic", req.topic)
            if "payload" not in data_to_save:
                # Nếu không có payload, lấy toàn bộ data làm payload
                data_to_save["payload"] = str(req.data)
            # value là optional, không cần check
            
        elif req.table_name == "values":
            # Table values cần: data (float4), date (optional)
            if "data" not in data_to_save:
                raise HTTPException(400, "Table 'values' cần field 'data' (float)")
            # date và created_at tự động bởi DB
            
        elif req.table_name == "history":
            # Table history cần: performer, date, value
            data_to_save.setdefault("performer", user.get("email"))
            if "value" not in data_to_save:
                raise HTTPException(400, "Table 'history' cần field 'value' (float)")
            # date tự động bởi DB nếu không có
            
        elif req.table_name == "users":
            # ⚠️ CHÚ Ý: Không nên dùng endpoint /publish để tạo user
            # Hãy dùng endpoint /register thay vì gửi vào table users trực tiếp
            raise HTTPException(
                400, 
                "Không thể tạo user qua endpoint này. Vui lòng dùng POST /register với {name, email, password}"
            )

        # Publish MQTT với thông tin đầy đủ
        mqtt_payload = {
            "table_name": req.table_name,
            **data_to_save
        }
        publish_to_mqtt(req.topic, mqtt_payload)

        # Lưu vào Supabase
        saved = save_to_supabase(req.table_name, data_to_save)
        
        if not saved:
            raise HTTPException(500, "Không thể lưu vào database")

        return {
            "status": "success",
            "saved_to": req.table_name,
            "mqtt_topic": req.topic,
            "saved_data": saved,
            "user": user["email"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Lỗi server: {str(e)}")

@app.get("/")
def home():
    return {"message": "Backend + Supabase running!"}

if __name__ == "__main__":
    port = int(os.getenv("BACKEND_PORT", 10000))
    # uvicorn.run(host='127.0.0.1', port=port, app="main:app", reload=True)
    uvicorn.run(host='0.0.0.0', port=port, app="main:app")