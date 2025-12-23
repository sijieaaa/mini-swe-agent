import os
from pathlib import Path
import platform

import yaml
from dotenv import load_dotenv
import json

from minisweagent.agents.default import DefaultAgent
from minisweagent.environments.docker import DockerEnvironment
from minisweagent.models.litellm_model import LitellmModel

load_dotenv()

task = "write a simple python code. Save it to `/tmp/123.py`"


model_name = "openai/gpt-5-mini"
# model_name = "openai/deepseek-v3.2"

container_name = "test"

yaml_abspath = "/data/sijie/cann/mini-swe-agent/src/minisweagent/config/mini.yaml"
yaml_content = yaml.safe_load(Path(yaml_abspath).read_text())

agent = DefaultAgent(
    LitellmModel(
        model_name=model_name,
        model_kwargs={
            "api_key": os.environ["AQIAPI_API_KEY"],
            "api_base": os.environ["AQIAPI_API_BASE_URL"],
        },
    ),
    DockerEnvironment(
        container_name=container_name,
    ),
    **yaml_content["agent"],
)

uname = platform.uname()
status = agent.run(
    task,
    system=uname.system,
    release=uname.release,
    version=uname.version,
    machine=uname.machine,
)
traj = agent.messages

with open("traj.jsonl", "w") as f:
    for e in traj:
        f.write(json.dumps(e) + "\n")
None
