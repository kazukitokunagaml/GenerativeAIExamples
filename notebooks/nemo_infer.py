# SPDX-FileCopyrightText: Copyright (c) 2023 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
from functools import partial
from typing import Any, Callable, Dict, List, Optional

import requests
from langchain.callbacks.manager import CallbackManagerForLLMRun
from langchain.llms.base import LLM


class NemoInfer(LLM):
    """A custom Langchain LLM class that integrates with NemoInfer MS.

    Arguments:
    server_url: (str) The URL of the NemoInfer MS to use.
    model_name: (str) The name of the NemoInfer MS model to use.
    temperature: (str) Temperature to use for sampling
    top_p: (float) The top-p value to use for sampling
    stop: (List[str]) The words indicate stop generation of response
    frequency_penalty: (float): penalty to each token that appears more frequently
    streaming: (bool): Stream response
    tokens: (int) The maximum number of tokens to generate.
    """
    model: str = "llama"
    temperature: Optional[float] = 1
    stop: Optional[List[str]] = ["</s>", "<extra_id_1>"]
    n: Optional[int] = 1
    top_p: Optional[float] = 0.01
    frequency_penalty: Optional[float] = 0
    server_url: Optional[str] = "http://localhost:9999"
    streaming: Optional[bool] = True
    tokens: Optional[int] = 50 # This corresponds with max_tokens in openai schema

    @property
    def _llm_type(self) -> str:
        return "NemoInfer"

    @property
    def _default_params(self) -> Dict[str, Any]:
        """Get the default parameters for calling NemoInfer MS API."""

        normal_params: Dict[str, Any] = {
            "frequency_penalty": self.frequency_penalty,
            "n": self.n,
            "model": self.model,
            "max_tokens": self.tokens,
            "stream": self.streaming
        }

        # Either temperature or top_p should be set not both
        if self.temperature:
            normal_params["temperature"] = self.temperature
        elif self.top_p:
            normal_params["top_p"] = self.top_p

        return {**normal_params}

    def _stream_response_to_generation_chunk(self, chunk):
        """parse json response from nemo ms api
        """
        try:
            chunk = json.loads(chunk)
            chunk = chunk.get("choices", [{}])[0].get("text", "")
            return chunk
        except Exception as e:
            return ""

    def _call(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> str:
        """
        Execute an inference request.

        Args:
            prompt: The prompt to pass into the model.
            stop: A list of strings to stop generation when encountered

        Returns:
            The string generated by the model
        """

        text_callback = None
        # Register text_callback for streaming response
        if run_manager:
            text_callback = partial(run_manager.on_llm_new_token, verbose=self.verbose)

        if stop is None:
            stop = self.stop

        # Request to Nemo Infer MS
        data = {"prompt": prompt, "stop": stop, **self._default_params}
        # Nemo MS uses max_tokens instead of token
        if "tokens" in kwargs:
            data["max_tokens"] = kwargs.get("tokens")

        if self.streaming:
            return self._streaming_request(
                data, text_callback, **kwargs
            )
        try:
            response = requests.post(self.server_url, json=data)
            resp = response.json()
            resp = resp.get("choices", [{}])[0].get("text", "")
            return resp
        except Exception as e:
            print(f"Exception: {e} while generating response")
            return ""

    def _streaming_request(
        self,
        data: Dict[str, Any],
        text_callback: Optional[Callable[[str], None]] = None,
        **kwargs: Any,
    ) -> str:
        """parse streaming response from nemo ms api
        """
        response = requests.post(self.server_url, json=data, stream=True)
        current_string = ""
        resp = ""

        # Check the response status
        if response.status_code == 200:
            for chunk in response.iter_lines():
                chunk = chunk.decode("utf-8")
                if chunk:
                    # data: is appended before every chunk, remove it to parse json
                    chunk = chunk.lstrip("data: ")
                    chunk = self._stream_response_to_generation_chunk(chunk)
                    # Unlike openai ms returns complete response instead of token
                    # find new generated chunk and send it for streaming
                    resp = chunk[len(current_string) :]

                    # Nemo Infer MS sends stop words along response
                    if resp in data.get("stop", self.stop):
                        continue
                    if text_callback:
                        text_callback(resp)
                    current_string = chunk
        return resp
