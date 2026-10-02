from copy import deepcopy

from lfx.custom.custom_component.component import Component
from lfx.io import Output
from lfx.schema.data import Data


class ResponsesInput(Component):
    display_name = "Responses Input"
    description = "Read the Responses API input and file IDs for this run."
    icon = "Paperclip"
    name = "ResponsesInput"

    inputs = []
    outputs = [Output(display_name="Input", name="input_data", method="read_input")]

    def read_input(self) -> Data:
        input_value = deepcopy(self.ctx.get("responses_input", []))
        file_ids = []
        if isinstance(input_value, list):
            for message in input_value:
                content = message.get("content")
                if isinstance(content, list):
                    file_ids.extend(
                        part["file_id"]
                        for part in content
                        if isinstance(part, dict) and part.get("type") == "input_file"
                    )
        return Data(data={"input": input_value, "file_ids": file_ids})
