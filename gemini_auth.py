# import os
# import json
# from google.oauth2 import service_account
# from google.auth.transport.requests import Request

# def get_access_token():
#     try:
#         # Load service account JSON from env variable
#         service_account_info = json.loads(os.getenv("SERVICE_ACCOUNT_FILE"))
#         print(service_account_info)
        
#         credentials = service_account.Credentials.from_service_account_info(
#             service_account_info,
#             scopes=["https://www.googleapis.com/auth/cloud-platform"]
#         )
#         credentials.refresh(Request())
#         return credentials.token

#     except Exception as e:
#         print("Error getting access token:", e)
#         return None

# get_access_token()

import os
from google.oauth2 import service_account
import google.auth.transport.requests

def get_access_token():
    creds_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_path or not os.path.exists(creds_path):
        raise FileNotFoundError("Service account file not found or environment variable not set")

    try:
        creds = service_account.Credentials.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        auth_req = google.auth.transport.requests.Request()
        creds.refresh(auth_req)
        return creds.token
    except Exception as e:
        raise RuntimeError(f"Error getting access token: {e}")


