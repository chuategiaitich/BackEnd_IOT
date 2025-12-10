1. API list: (HTTPS)
__________________________
____ for frontend dev ____

Backend_API_domain     :

GET  /                 :  Check backend live

POST /register         :  Register command

POST /login            :  Login command

POST /create-profile   :  Create profile manually if error

POST /publish          :  Call command

    List command of /publish:

        - "messages" (for communicate among clients)
              |
              |-------"topic" (string)
              |
              |-------"payload" (string)
              |
              |-------"value" (float8)

        - "values"  (for realtime data update)
              |
              |-------"data" (float8)
              |
              |-------"date" (optional - date)

        - "history" (for history update)
              |
              |-------"performer" (user email - string)
              |
              |-------"date" (date)
              |
              |-------"value" (float 8)
__________________________


2. EMQX list (MQTT)
__________________________
____ for embeded dev ____

MQTT_BROKER    =  a12145b1.ala.asia-southeast1.emqxsl.com

MQTT_PORT      =  8883

MQTT_USERNAME  =  embeded_device

MQTT_PASSWORD  =  123123

__________________________

