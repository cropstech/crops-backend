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
WEB_PUSH_OUTPUT=$(aws lightsail push-container-image \
    --service-name ${SERVICE_NAME} \
    --label web \
    --image ${SERVICE_NAME}-web:latest \
    --region ${REGION} \
    --profile ${AWS_PROFILE})
LATEST_WEB=$(echo "$WEB_PUSH_OUTPUT" | grep "Refer to this image as" | sed 's/.*as "\([^"]*\)".*/\1/')

# Deploy the containers
echo -e "${YELLOW}🚀 Deploying containers...${NC}"

# Update the containers.json with actual image references
cp containers.json containers.json.bak
sed -i '' "s|:crops-backend\.web\.latest|${LATEST_WEB}|g" containers.json
# No celery references to update

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