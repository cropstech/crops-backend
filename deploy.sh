#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SERVICE_NAME="crops-backend"
REGION="us-east-2"  # Change to your preferred region
AWS_PROFILE="crops-deploy"  # AWS profile to use

echo -e "${GREEN}🚀 Deploying Crops Backend with Automated Migrations${NC}"

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

# Build Docker images
echo -e "${YELLOW}📦 Building Docker images...${NC}"
docker build --platform linux/amd64 -t ${SERVICE_NAME}-web:latest .

# Push images to Lightsail container registry
echo -e "${YELLOW}📤 Pushing images to Lightsail container registry...${NC}"

# Check if container service exists
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
WEB_PUSH_OUTPUT=$(aws lightsail push-container-image \
    --service-name ${SERVICE_NAME} \
    --label web \
    --image ${SERVICE_NAME}-web:latest \
    --region ${REGION} \
    --profile ${AWS_PROFILE} 2>&1)
LATEST_WEB=$(echo "$WEB_PUSH_OUTPUT" | awk -F '"' '/Refer to this image as/ {print $2; exit}')

# Validate image reference
if [ -z "$LATEST_WEB" ] || ! echo "$LATEST_WEB" | grep -Eq '^:[a-z0-9-]+\.web\.[0-9]+'; then
    echo -e "${RED}❌ Failed to parse Lightsail image reference from push output.${NC}"
    echo "$WEB_PUSH_OUTPUT"
    exit 1
fi
echo -e "${GREEN}✅ Using web image reference: ${LATEST_WEB}${NC}"

# Prepare deployment configuration
echo -e "${BLUE}🔧 Preparing deployment configuration with migrations...${NC}"

# Use the migration-enabled configuration
cp containers.json containers-deploy.json

# Update image references in deployment config
sed -i '' "s|:crops-backend\.web\.latest|${LATEST_WEB}|g" containers-deploy.json
echo -e "${GREEN}✅ Updated containers-deploy.json image to: ${LATEST_WEB}${NC}"

# Sync environment variables from .env.production
if [ -f ".env.production" ]; then
    echo -e "${YELLOW}🔄 Syncing .env.production into deployment configuration...${NC}"

    # Check required tools
    if ! command -v jq >/dev/null 2>&1; then
        echo -e "${RED}❌ 'jq' is required but not installed. Please install jq and re-run.${NC}"
        echo -e "${YELLOW}   macOS: brew install jq${NC}"
        exit 1
    fi
    if ! command -v python3 >/dev/null 2>&1; then
        echo -e "${RED}❌ 'python3' is required but not installed. Please install Python 3 and re-run.${NC}"
        exit 1
    fi

    # Convert .env.production to JSON
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

# Ensure settings module is set for production
data.setdefault('DJANGO_SETTINGS_MODULE', 'crops.settings_production')

print(json.dumps(data))
PY
)

    # Validate and apply environment variables to web container
    echo "$ENV_JSON" | jq -c . > /dev/null || {
        echo -e "${RED}❌ Failed to parse .env.production into JSON. Please check the file format.${NC}"
        exit 1
    }

    TMP_JSON=$(mktemp)
    jq --argjson env "$ENV_JSON" \
       '.containers.web.environment = ((.containers.web.environment // {}) + $env) | .containers.worker.environment = ((.containers.worker.environment // {}) + $env)' \
       containers-deploy.json > "$TMP_JSON" && mv "$TMP_JSON" containers-deploy.json
    echo -e "${GREEN}✅ Applied environment variables to web and worker containers${NC}"
else
    echo -e "${YELLOW}⚠️  .env.production not found; using default environment${NC}"
fi

# Deploy with migrations
echo -e "${BLUE}🚀 Deploying with automated migrations...${NC}"
echo -e "${YELLOW}   1. Migrations will run before web server starts${NC}"
echo -e "${YELLOW}   2. Web server will only start if migrations succeed${NC}"

aws lightsail create-container-service-deployment \
    --service-name ${SERVICE_NAME} \
    --cli-input-json file://containers-deploy.json \
    --region ${REGION} \
    --profile ${AWS_PROFILE}

# Clean up temporary files
rm containers-deploy.json

echo -e "${GREEN}✅ Deployment initiated with automated migrations!${NC}"
echo -e "${YELLOW}⏳ Waiting for deployment to complete...${NC}"

# Check deployment status
echo -e "${YELLOW}⏳ Monitoring deployment progress...${NC}"
sleep 30

# Get deployment status
DEPLOYMENT_STATUS=$(aws lightsail get-container-service-deployments \
    --service-name ${SERVICE_NAME} \
    --region ${REGION} \
    --profile ${AWS_PROFILE} \
    --query 'deployments[0].state' \
    --output text)

echo -e "${BLUE}📊 Deployment status: ${DEPLOYMENT_STATUS}${NC}"

# Get the public endpoint
ENDPOINT=$(aws lightsail get-container-services \
    --service-name ${SERVICE_NAME} \
    --region ${REGION} \
    --profile ${AWS_PROFILE} \
    --query 'containerServices[0].url' \
    --output text)

if [ "$DEPLOYMENT_STATUS" = "ACTIVE" ]; then
    echo -e "${GREEN}🎉 Deployment completed successfully!${NC}"
    echo -e "${GREEN}✅ Migrations completed automatically${NC}"
    echo -e "${GREEN}🌐 Your application is available at: ${ENDPOINT}${NC}"
else
    echo -e "${YELLOW}⏳ Deployment still in progress. Status: ${DEPLOYMENT_STATUS}${NC}"
    echo -e "${BLUE}💡 Check migration logs with:${NC}"
    echo -e "${BLUE}   aws lightsail get-container-log --service-name ${SERVICE_NAME} --container-name web --region ${REGION} --profile ${AWS_PROFILE}${NC}"
fi

# Display container status
echo -e "${BLUE}📊 Container deployment details:${NC}"
aws lightsail get-container-service-deployments \
    --service-name ${SERVICE_NAME} \
    --region ${REGION} \
    --profile ${AWS_PROFILE} \
    --query 'deployments[0].containers' \
    --output table
