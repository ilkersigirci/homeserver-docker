import json
from copy import deepcopy
from urllib.parse import quote

from lfx.components.data_source.api_request import APIRequestComponent
from lfx.custom.custom_component.component import Component
from lfx.io import DataInput, IntInput, MessageInput, Output, SecretStrInput, StrInput
from lfx.schema.data import Data
from lfx.schema.message import Message
from lfx.utils.secrets import secret_value_to_str


class OpenaiFilesAPI(Component):
    display_name = "OpenaiFilesAPI"
    description = "Add external file contents to a chat message, or preserve Playground attachments."
    icon = "Paperclip"
    name = "OpenaiFilesAPI"

    inputs = [
        MessageInput(name="message", display_name="Chat Input", required=True),
        DataInput(
            name="responses_input",
            display_name="Responses Input",
            info="Connect the JSON output of Responses Input.",
            required=True,
        ),
        StrInput(
            name="api_base",
            display_name="Files API Base URL",
            info="Base URL including /v1, for example https://files.example.com/v1. Required when file IDs are present.",
        ),
        SecretStrInput(
            name="api_key",
            display_name="Files API Key",
            info="Optional bearer token for the Files API.",
        ),
        IntInput(name="timeout", display_name="Timeout", value=30, info="Seconds per file request.", advanced=True),
    ]
    outputs = [Output(display_name="Message", name="message_output", method="build_message")]

    async def build_message(self) -> Message:
        if not isinstance(self.responses_input, Data):
            raise ValueError("Connect Responses Input to the Responses Input port.")
        file_ids = self.responses_input.data.get("file_ids")
        if not isinstance(file_ids, list) or any(
            not isinstance(file_id, str) or not file_id.strip() or file_id in {".", ".."}
            for file_id in file_ids
        ):
            raise ValueError("Responses Input must contain a list of non-empty file IDs.")
        if not file_ids:
            self.status = self.message
            return self.message

        api_base = (self.api_base or "").strip().rstrip("/")
        if not api_base:
            raise ValueError("Files API Base URL is required when external file IDs are present.")
        headers = [{"key": "Accept", "value": "application/json"}]
        api_key = secret_value_to_str(self.api_key) if self.api_key else ""
        if api_key:
            headers.append({"key": "Authorization", "value": f"Bearer {api_key}"})

        documents = []
        for file_id in dict.fromkeys(file_ids):
            # Reuse Langflow's URL validation, network policy, and JSON decoding.
            request = APIRequestComponent(
                url_input=f"{api_base}/files/{quote(file_id, safe='')}/content",
                method="GET",
                headers=headers,
                timeout=self.timeout,
                follow_redirects=False,
                save_to_file=False,
            )
            response = await request.make_api_request()
            status_code = response.data.get("status_code", 0)
            if not 200 <= status_code < 300:
                raise ValueError(f"Files API request failed for {file_id} (HTTP {status_code}).")
            if "result" not in response.data or isinstance(response.data["result"], bytes):
                raise ValueError(f"Files API content for {file_id} must be JSON.")
            documents.append({"file_id": file_id, "content": response.data["result"]})

        # Langflow's inherited __deepcopy__ does not preserve the Message type.
        message = await Message.create(**deepcopy(self.message.model_dump()))
        context = json.dumps(documents, ensure_ascii=False, indent=2)
        message.text = f"{message.text}\n\nFile contents (JSON):\n{context}".strip()
        self.status = message
        return message
