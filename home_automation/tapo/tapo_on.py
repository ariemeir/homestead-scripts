# tapo_on.py
import asyncio
from tapo import ApiClient
from tapo_common import get_password_from_keychain
import os

IP = os.environ.get("TAPO_IP", "192.168.1.17")   # fallback if not set
ACCOUNT = os.environ.get("TAPO_EMAIL", "arie.coach@gmail.com")
SERVICE = os.environ.get("TAPO_KEYCHAIN_SERVICE", "tapo")  # use same name you saved in Keychain

async def main():
    password = get_password_from_keychain(ACCOUNT, SERVICE)
    client = ApiClient(ACCOUNT, password)
    # p110 returns a coroutine that must be awaited
    plug = await client.p110(IP)
    await plug.on()
    print("P110M is now ON")

if __name__ == "__main__":
    asyncio.run(main())

