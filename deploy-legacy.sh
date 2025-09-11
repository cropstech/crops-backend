#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
SERVICE_NAME="crops-backend"
REGION="us-east-2"  # Change to your preferred region
AWS_PROFILE="crops-deploy"  # AWS profile to use

echo -e "${GREEN}🚀 Deploying Crops Backend to AWS Lightsail Containers${NC}"

# Check if AWS CLI is installed
if ! command -v aws &> /dev/null; then
    echo -e "${RED}❌ AWS CLI is not installed. Please install it first.${NC}"
    exit 1
fi

# Check if logged in to AWS with profile
if ! aws sts get-caller-identity --profile ${AWS_PROFILE} &> /dev/null; then
    echo -e "${RED}❌ Not logged in to AWS profile '${AWS_PROFILE}'. Please run 'aws configure --profile ${AWS_PROFILE}' first.${NC}"
    exit 1
fi

# Build and push Docker images
echo -e "${YELLOW}📦 Building Docker images...${NC}"

# Build web container for linux/amd64 platform
docker build --platform linux/amd64 -t ${SERVICE_NAME}-web:latest .

# Push images to Lightsail container registry
echo -e "${YELLOW}📤 Pushing images to Lightsail container registry...${NC}"

# Get push commands from Lightsail
aws lightsail get-container-images --service-name ${SERVICE_NAME} --region ${REGION} --profile ${AWS_PROFILE} > /dev/null 2>&1 || {
    echo -e "${YELLOW}⚠️  Container service doesn't exist. Creating it first...${NC}"
    aws lightsail create-container-service \
        --service-name ${SERVICE_NAME} \
        --power small \
        --scale 1 \
        --region ${REGION} \
        --profile ${AWS_PROFILE}
    
    echo -e "${YELLOW}⏳ Waiting for container service to be ready...${NC}"
    aws lightsail wait container-service-deployed --service-name ${SERVICE_NAME} --region ${REGION} --profile ${AWS_PROFILE}
}

# Push web image and capture the reference
# Capture combined stdout/stderr to ensure the reference hint is included
WEB_PUSH_OUTPUT=$(aws lightsail push-container-image \
    --service-name ${SERVICE_NAME} \
    --label web \
    --image ${SERVICE_NAME}-web:latest \
    --region ${REGION} \
    --profile ${AWS_PROFILE} 2>&1)
LATEST_WEB=$(echo "$WEB_PUSH_OUTPUT" | awk -F '"' '/Refer to this image as/ {print $2; exit}')

# Validate that we extracted a Lightsail image reference like ":crops-backend.web.N"
if [ -z "$LATEST_WEB" ] || ! echo "$LATEST_WEB" | grep -Eq '^:[a-z0-9-]+\.web\.[0-9]+'; then
    echo -e "${RED}❌ Failed to parse Lightsail image reference from push output.${NC}"
    echo "$WEB_PUSH_OUTPUT"
    exit 1
fi
echo -e "${GREEN}✅ Using web image reference: ${LATEST_WEB}${NC}"

# Deploy the containers
echo -e "${YELLOW}🚀 Deploying containers...${NC}"

# Update the containers.json with actual image references
cp containers.json containers.json.bak
sed -i '' "s|:crops-backend\.web\.latest|${LATEST_WEB}|g" containers.json
echo -e "${YELLOW}🔧 Updated containers.json image to: ${LATEST_WEB}${NC}"
# Background jobs handled by Chancy worker container

# Sync .env.production into containers.json environment (if present)
if [ -f ".env.production" ]; then
    echo -e "${YELLOW}🔄 Syncing .env.production into containers.json environment...${NC}"

    # Ensure required tools are available
    if ! command -v jq >/dev/null 2>&1; then
        echo -e "${RED}❌ 'jq' is required but not installed. Please install jq and re-run.${NC}"
        echo -e "${YELLOW}   macOS: brew install jq${NC}"
        exit 1
    fi
    if ! command -v python3 >/dev/null 2>&1; then
        echo -e "${RED}❌ 'python3' is required but not installed. Please install Python 3 and re-run.${NC}"
        exit 1
    fi

    # Convert .env.production to a JSON object
    ENV_JSON=$(python3 - <<'PY'
import json
import os

env_file = ".env.production"
data = {}
try:
    with open(env_file) as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            if '=' not in line:
                continue
            key, val = line.split('=', 1)
            key = key.strip()
            val = val.strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            data[key] = val
except FileNotFoundError:
    pass

# Ensure settings module is set for production unless explicitly provided
data.setdefault('DJANGO_SETTINGS_MODULE', 'crops.settings_production')

print(json.dumps(data))
PY
)

    # Validate JSON and merge with existing environment (env values override existing)
    echo "$ENV_JSON" | jq -c . > /dev/null || {
        echo -e "${RED}❌ Failed to parse .env.production into JSON. Please check the file format.${NC}"
        exit 1
    }

    TMP_JSON=$(mktemp)
    jq --argjson env "$ENV_JSON" \
       '.containers.web.environment = ((.containers.web.environment // {}) + $env)' \
       containers.json > "$TMP_JSON" && mv "$TMP_JSON" containers.json
    echo -e "${GREEN}✅ Injected environment variables from .env.production into containers.json${NC}"
else
    echo -e "${YELLOW}⚠️  .env.production not found; skipping env sync into containers.json${NC}"
fi

# Deploy the updated configuration
aws lightsail create-container-service-deployment \
    --service-name ${SERVICE_NAME} \
    --cli-input-json file://containers.json \
    --region ${REGION} \
    --profile ${AWS_PROFILE}

# Restore the original configuration file
mv containers.json.bak containers.json

echo -e "${GREEN}✅ Deployment initiated successfully!${NC}"
echo -e "${YELLOW}⏳ Waiting for deployment to complete...${NC}"

# Check deployment status (no wait command available for Lightsail)
echo -e "${YELLOW}⏳ Checking deployment status...${NC}"
sleep 10

# Get the public endpoint
ENDPOINT=$(aws lightsail get-container-services --service-name ${SERVICE_NAME} --region ${REGION} --profile ${AWS_PROFILE} --query 'containerServices[0].url' --output text)

echo -e "${GREEN}🎉 Deployment completed successfully!${NC}"
echo -e "${GREEN}🌐 Your application is available at: ${ENDPOINT}${NC}"

# Display container status
echo -e "${YELLOW}📊 Container status:${NC}"
aws lightsail get-container-service-deployments --service-name ${SERVICE_NAME} --region ${REGION} --profile ${AWS_PROFILE} --query 'deployments[0].containers'