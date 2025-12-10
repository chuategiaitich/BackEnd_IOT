import paho.mqtt.client as mqtt
import os
from dotenv import load_dotenv
import ssl
from supabase import create_client, Client
import json

load_dotenv()

# MQTT Config
broker = os.getenv("MQTT_BROKER")
port = int(os.getenv("MQTT_PORT", 8883))
username = os.getenv("MQTT_USERNAME")
password = os.getenv("MQTT_PASSWORD")

# Supabase Config
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

supabase: Client = None

client = mqtt.Client(
    client_id="backend-petfeeder-2025",
    callback_api_version=mqtt.CallbackAPIVersion.VERSION2
)

def init_supabase():
    global supabase
    supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    print("Supabase client khởi tạo thành công!")

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("Backend → EMQX: Đã kết nối & subscribe #")
        client.subscribe("#", qos=1)
    else:
        print(f"MQTT kết nối thất bại: {rc}")

def on_message(client, userdata, msg):
    payload = msg.payload.decode('utf-8')
    print(f"MQTT Received → {msg.topic} : {payload}")

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        # Nếu không phải JSON, lưu như plain text vào messages
        data = {"payload": payload}
        table_name = "messages"
    else:
        # Lấy table_name từ data, SAU ĐÓ XÓA NÓ khỏi data
        table_name = data.pop("table_name", "messages")

    # Lưu vào Supabase với topic từ MQTT
    save_to_supabase(table_name, data, topic=msg.topic)

def save_to_supabase(table_name: str, data: dict, topic: str = None):
    """
    Lưu dữ liệu vào table được chỉ định
    
    Args:
        table_name: Tên table (messages, values, history, users)
        data: Dict dữ liệu cần insert
        topic: MQTT topic (chỉ dùng cho table messages)
    
    Returns:
        Dict của record vừa insert hoặc None nếu lỗi
    """
    if supabase is None:
        print("Supabase client chưa khởi tạo!")
        return None

    final_data = data.copy()

    # Xử lý đặc biệt cho từng table
    if table_name == "messages":     #id, topic, payload, created_at, value
        # Table messages: cần topic và payload
        if topic:
            final_data.setdefault("topic", topic)
        if "payload" not in final_data:
            final_data["payload"] = str(data)
        # value là optional
        
    elif table_name == "values":    #id, data, date, created_at
        # Table values: cần data (float)
        if "data" not in final_data:
            print(f"WARNING: Table 'values' thiếu field 'data', skip insert")
            return None
            
    elif table_name == "history":
        # Table history: insert performer, value, và date (nếu có, không thì set default now())
        # Bỏ field thừa như action, amount
        if "value" not in final_data:
            print(f"WARNING: Table 'history' thiếu field 'value', skip insert")
            return None
        from datetime import datetime  # Import ở đây nếu chưa có
        final_data = {
            "performer": final_data.get("performer"),
            "value": final_data.get("value"),
            "date": final_data.get("date") if "date" in final_data else datetime.now().isoformat()  # Default nếu null
        }  # created_at tự động bởi DB
        
    elif table_name == "users":     #id, email, created_at, name
        # Table users: cần name, email (password do Supabase Auth quản lý)
        required = ["name", "email"]
        missing = [f for f in required if f not in final_data]
        if missing:
            print(f"WARNING: Table 'users' thiếu các field: {missing}, skip insert")
            return None
        # Xóa password nếu có (không tồn tại trong schema)
        final_data.pop("password", None)

    try:
        response = supabase.table(table_name).insert(final_data).execute()
        
        if response.data:
            print(f"✅ ĐÃ LƯU VÀO TABLE '{table_name}' → {final_data}")
            return response.data[0]
        else:
            print(f"❌ Lưu thất bại vào '{table_name}': {response}")
            return None
            
    except Exception as e:
        print(f"❌ Exception khi insert vào '{table_name}': {e}")
        return None

def setup_mqtt():
    init_supabase()
    client.tls_set(tls_version=ssl.PROTOCOL_TLS)
    client.username_pw_set(username, password)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(broker, port, keepalive=60)
    client.loop_start()
    print("MQTT loop đã khởi động!")

def publish_to_mqtt(topic: str, message: str | dict):
    if isinstance(message, dict):
        message = json.dumps(message, ensure_ascii=False)
    result = client.publish(topic, message, qos=1)
    print(f"📤 Published → {topic} : {message}")
    return result