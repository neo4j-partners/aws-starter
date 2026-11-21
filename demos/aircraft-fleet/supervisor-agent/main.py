"""AgentCore Runtime entrypoint. The runtime runs this file and expects port 8080."""

from fleet_supervisor.server import main

if __name__ == "__main__":
    main(default_port=8080)
