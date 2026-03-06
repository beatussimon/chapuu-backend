import requests
import sys
import uuid

def test_registration():
    url = "http://127.0.0.1:8000/api/register/"
    # Generate random username
    unique_user = f"testuser_{uuid.uuid4().hex[:8]}"
    payload = {
        "username": unique_user,
        "password": "testpassword123",
        "phone_number": "555-0101"
    }
    
    try:
        response = requests.post(url, json=payload)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        if response.status_code == 201:
            print("SUCCESS: Registration endpoint works!")
            sys.exit(0)
        else:
            print("FAILED: Registration endpoint returned an error.")
            sys.exit(1)
    except Exception as e:
        print(f"Connection error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    test_registration()
