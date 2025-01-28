STACK_NAME=desktop_apps
cd /home/ilker/docker/stacks/${STACK_NAME}

# For each service in docker-compose.yml
for service in $(yq '.services | keys | .[]' docker-compose.yml); do
  yq eval '
    {
      "services": {
        "'$service'": .services["'$service'"] * {
          "profiles": ["'$STACK_NAME'"]
        }
      }
    }
  ' docker-compose.yml > "${service}.yml"
done
