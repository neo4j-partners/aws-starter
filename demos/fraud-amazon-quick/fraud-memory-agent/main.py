"""AgentCore Runtime entrypoint. The runtime runs this file and expects port 8080.

CodeZip installs the dependencies but not this project, so the Runtime cannot
run the ``fraud-server`` script. This file sits at the zip root, which puts
``core`` and ``server`` on the import path.
"""

from server.runtime_app import main

if __name__ == "__main__":
    main(default_port=8080, local=False)
