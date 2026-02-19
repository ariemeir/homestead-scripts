# tapo_off.py
import asyncio
from tapo import ApiClient
from tapo_common import get_password_from_keychain
import os

IP = os.environ.get("TAPO_IP", "192.168.1.17")
ACCOUNT = os.environ.get("TAPO_EMAIL", "arie.coach@gmail.com")
SERVICE = os.environ.get("TAPO_KEYCHAIN_SERVICE", "tapo")

async def main():
    password = get_password_from_keychain(ACCOUNT, SERVICE)
    client = ApiClient(ACCOUNT, password)
    plug = await client.p110(IP)
    await plug.off()
    print("P110M is now OFF")

if __name__ == "__main__":
    asyncio.run(main())

