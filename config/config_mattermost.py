import os
from dotenv import load_dotenv

load_dotenv()

# Mattermost client connection configuration
mattermost_client_config = {
    "url": os.getenv("MATTERMOST_URL"),
    "token": os.getenv("MATTERMOST_TOKEN"),
    "channel_id": os.getenv("MATTERMOST_CHANNEL_ID"),
    "team": os.getenv("MATTERMOST_TEAM"),
}
