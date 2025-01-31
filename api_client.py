import aiohttp
import requests
import logging

# Logger einrichten
logger = logging.getLogger("APIClientLogger")
logger.setLevel(logging.INFO)
handler = logging.FileHandler("api_client.log", encoding="utf-8")
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

class APIClient:
    def __init__(self, base_url, token):
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}

    async def get(self, endpoint):
        """Sendet eine GET-Anfrage asynchron."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        return await response.text()
                    else:
                        logger.error(f"GET-Anfrage fehlgeschlagen: {url}, Status: {response.status}, Response: {await response.text()}")
                        return None
        except Exception as e:
            logger.error(f"Fehler bei GET-Anfrage: {url}, Fehler: {str(e)}")
            return None

    async def post(self, endpoint, data):
        """Sendet eine POST-Anfrage asynchron."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.post(url, json=data) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        logger.error(f"POST-Anfrage fehlgeschlagen: {url}, Status: {response.status}, Response: {await response.text()}")
                        return None
        except Exception as e:
            logger.error(f"Fehler bei POST-Anfrage: {url}, Fehler: {str(e)}")
            return None

    def sync_get(self, endpoint):
        """Sendet eine GET-Anfrage synchron."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            response = requests.get(url, headers=self.headers)
            if response.status_code == 200:
                return response.text
            else:
                logger.error(f"Sync GET-Anfrage fehlgeschlagen: {url}, Status: {response.status_code}, Response: {response.text}")
                return None
        except Exception as e:
            logger.error(f"Fehler bei Sync GET-Anfrage: {url}, Fehler: {str(e)}")
            return None

    def sync_post(self, endpoint, data):
        """Sendet eine POST-Anfrage synchron."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            response = requests.post(url, json=data, headers=self.headers)
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Sync POST-Anfrage fehlgeschlagen: {url}, Status: {response.status_code}, Response: {response.text}")
                return None
        except Exception as e:
            logger.error(f"Fehler bei Sync POST-Anfrage: {url}, Fehler: {str(e)}")
            return None
