from phi.assistant import Assistant
from phi.llm.anthropic import Claude
from phi.llm.openai import OpenAIChat
from phi.tools.duckduckgo import DuckDuckGo
import requests
import json
from typing import Optional
from thefuzz import fuzz
from dotenv import load_dotenv
import os
import asyncio
from aio_pika import connect_robust
from aio_pika.patterns import RPC

# Load environment variables from .env file
load_dotenv()

class HomeAssistant:
    def __init__(self):
        self.base_url = os.getenv('HOME_ASSISTANT_BASE_URL')
        self.headers = {
            "Authorization": f"Bearer {os.getenv('HOME_ASSISTANT_ACCESS_TOKEN')}",
            "Content-Type": "application/json",
        }

    def call_service(self, domain, service, entity_id, **kwargs):
        """
        Generic method to call any Home Assistant service
        """
        url = f"{self.base_url}/api/services/{domain}/{service}"
        data = {"entity_id": entity_id, **kwargs}
        
        response = requests.post(url, headers=self.headers, json=data)
        
        if response.status_code == 200:
            return True
        else:
            print(f"Error: {response.status_code} - {response.text}")
            return False
        
    def get_entity_area(self, entity_id):
        """
        Get the area of a given entity in Home Assistant.

        Args:
        entity_id (str): The ID of the entity.

        Returns:
        str: The name of the area the entity belongs to, or None if not found.
        """
        template_url = f"{self.base_url}/api/template"
        template_data = {
            "template": f"{{{{ area_name('{entity_id}') }}}}"
        }

        response = requests.post(template_url, headers=self.headers, json=template_data)
        if response.status_code != 200:
            print(f"Error rendering template: {response.status_code}")
            print(f"Response content: {response.text}")
            return None

        area_name = response.text.strip()
        return area_name if area_name else None

    def turn_on_light(self, entity_id, brightness=None):
        """
        Turn on a light with optional brightness
        """
        data = {}
        if brightness is not None:
            # Convert percentage to 0-255 range
            brightness_value = int(brightness * 255 / 100)
            data["brightness"] = brightness_value
        return self.call_service("light", "turn_on", entity_id, **data)

    def turn_off_light(self, entity_id):
        """
        Turn off a light
        """
        return self.call_service("light", "turn_off", entity_id)

    def simple_get_state(self, entity_id):
        """
        Get the current state of an entity.
        """
        url = f"{self.base_url}/api/states/{entity_id}"
        
        response = requests.get(url, headers=self.headers)
        
        if response.status_code == 200:
            return response.json()['state']
        else:
            print(f"Error: {response.status_code} - {response.text}")
            return None
        


    def get_entity_info(self, entity_id: str) -> str:
        """
        Get the current state and attributes of an entity in Home Assistant.

        This function queries the Home Assistant API to retrieve the current state
        and attributes of a specified entity. It provides detailed information
        for complex entities like light bulbs, including brightness, color, etc.

        Args:
        entity_id (str): The unique identifier for the entity in Home Assistant.

        Returns:
        str: A JSON string containing the state and attributes of the entity if successful,
        or an error message if unsuccessful. This ensures that even in case of
        failure, some information is returned for the LLM to process.

        Example:
        >>> ha.get_state("light.living_room")
        '{"state": "on", "attributes": {"brightness": 255, "color_temp": 370, "friendly_name": "Living Room Light"}}'
        """
        url = f"{self.base_url}/api/states/{entity_id}"
        
        response = requests.get(url, headers=self.headers)
        
        if response.status_code == 200:
            data = response.json()
            return json.dumps({
                "state": data['state'],
                "area": self.get_entity_area(entity_id),
                "attributes": data['attributes']
            })
        else:
            return json.dumps({
                "error": f"Error: {response.status_code} - {response.text}"
            })

        
    def change_light_state(self, entity_id: str, state: bool, brightness: int = None) -> str:
        """
        Change the state of a smart light bulb.
        
        Args:
        entity_id (str): The unique identifier for the light bulb.
        state (bool): True to turn the light on, False to turn it off.
        brightness (int, optional): Brightness level as percent from 0 to 100. Defaults to None.
        
        Returns:
        str: A message indicating the result of the operation.
        """
        try:
            result = f"Changing light state for {entity_id}\n"
            
            if state:
                if self.turn_on_light(entity_id, brightness):
                    result += f"Turned light on"
                    if brightness is not None:
                        result += f" with brightness set to {brightness}%"
                else:
                    return f"Failed to turn on {entity_id}"
            else:
                if self.turn_off_light(entity_id):
                    result += f"Turned light off"
                else:
                    return f"Failed to turn off {entity_id}"
            
            new_state = self.simple_get_state(entity_id)
            result += f"\nCurrent state of {entity_id}: {new_state}"
            
            return result
        except Exception as e:
            return f"Error changing light state: {str(e)}"
    def search_smart_home_devices(self, query: str) -> str:
        """
        Perform a fuzzy keyword-based search for smart home devices in Home Assistant.
        
        Args:
        query (str): The search query.
        
        Returns:
        str: A JSON string containing a list of matching entities.
        """
        url = f"{self.base_url}/api/states"
        response = requests.get(url, headers=self.headers)
        
        if response.status_code == 200:
            all_entities = response.json()
            matching_entities = []
            
            for entity in all_entities:
                entity_id = entity['entity_id']
                friendly_name = entity['attributes'].get('friendly_name', '')
                

                # Perform fuzzy matching
                id_score = fuzz.partial_ratio(query.lower(), entity_id.lower())
                name_score = fuzz.partial_ratio(query.lower(), friendly_name.lower())
                
                if id_score > 70 or name_score > 70:  # Adjust threshold as needed
                    matching_entities.append({
                        "entity_id": entity_id,
                        "entity_name": friendly_name,
                        #"entity_state": entity['state'],
                        "entity_area": self.get_entity_area(entity_id),
                        #"entity_attributes": entity['attributes'],
                        "match_score": max(id_score, name_score)
                    })
            
            # Sort results by match score
            matching_entities.sort(key=lambda x: x['match_score'], reverse=True)
            
            return json.dumps(matching_entities)
        else:
            return json.dumps({"error": f"Error: {response.status_code} - {response.text}"})

class NodeSmartHomeAgent:
    def __init__(self):
        # Create a Home Assistant instance
        self.ha = HomeAssistant()

    async def call_llm(self, *, query: str) -> str:
        """
        Call the LLM with a query and return the response.
        Args:
        query (str): The query to send to the LLM.

        Returns:
        str: The response from the LLM.
        """

        # Define phidata assistant
        assistant = Assistant( # (had to move this here from init to solve a weird bug??? after 5 query completes it would stop calling functions????)
            #llm=Claude(model="claude-3-5-sonnet-20240620"),
            llm=OpenAIChat(model="gpt-4o-mini", temperature=0.3),
            description="You are a helpful smart home assistant.",
            instructions=["You can use tools to get information about or change the state of, smart home devices.",
                            "Changing the state of a smart home device will require searching for the entity ID of the device first.",
                            "If you need to use functions or tools, do it first before responding.",
                            "No yapping."],
            tools=[self.ha.search_smart_home_devices, self.ha.change_light_state, self.ha.get_entity_info], 
            show_tool_calls=False,
            read_chat_history=False,
            debug_mode=False,
            update_memory_after_run=False,
        )

        print(f"Recieved query: {query}")
        return await assistant.arun(query, stream=False)

async def main() -> None:
    connection = await connect_robust(
        "amqp://admin:adminpassword@192.168.0.52/",
        client_properties={"connection_name": "caller"},
    )

    # Creating channel
    channel = await connection.channel()

    nodeagent = NodeSmartHomeAgent()

    rpc = await RPC.create(channel)
    await rpc.register("call_node_smarthome_agent", nodeagent.call_llm, auto_delete=True)

    try:
        await asyncio.Future()
    finally:
        await connection.close()

if __name__ == "__main__":
    asyncio.run(main())