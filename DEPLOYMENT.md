# Crops Backend - AWS Lightsail Containers Deployment Guide

This guide provides comprehensive instructions for deploying the Crops Django backend to AWS Lightsail Containers with zero-downtime deployments.

## Overview

The deployment consists of:
- **Web Container**: Django application with Gunicorn
- **Chancy Worker**: Background job processing (replaces Celery)
- **PostgreSQL RDS**: Production database (also stores Chancy jobs)
- **ElastiCache Redis**: Caching and message broker

## Prerequisites

1. **AWS CLI** installed and configured
2. **Docker** installed and running
3. **AWS Account** with appropriate permissions
4. **Domain name** (optional but recommended)

## Quick Start

### 1. Initial Infrastructure Setup

Run the infrastructure setup script:

```bash
./setup-production.sh
```

This script will:
- Create RDS PostgreSQL instance
- Create ElastiCache Redis cluster
- Create Lightsail Container Service
- Generate `.env.production` template

### 2. Configure Environment Variables

Edit `.env.production` with your actual values:

```bash
cp .env.template .env.production
# Edit .env.production with your specific configuration
```

**Required updates:**
- AWS credentials and S3 bucket names
- Domain names for CORS and CSRF settings
- Frontend URL
- Asset Checker API URL and Lambda token

### 3. Deploy Application

Deploy the application:

```bash
./deploy.sh
```

This will:
- Build Docker images
- Push to Lightsail container registry
- Deploy with zero-downtime rolling updates

## Manual Deployment Steps

If you prefer manual deployment:

### 1. Create Infrastructure

```bash
# Create RDS PostgreSQL
aws rds create-db-instance \
    --db-instance-identifier crops-backend-db \
    --db-name crops_production \
    --db-instance-class db.t3.micro \
    --engine postgres \
    --master-username crops_admin \
    --master-user-password YOUR_SECURE_PASSWORD \
    --allocated-storage 20

# Create Redis Cache
aws elasticache create-cache-cluster \
    --cache-cluster-id crops-redis \
    --cache-node-type cache.t3.micro \
    --engine redis \
    --num-cache-nodes 1

# Create Container Service
aws lightsail create-container-service \
    --service-name crops-backend \
    --power small \
    --scale 2
```

### 2. Build and Push Images

```bash
# Build images
docker build -t crops-backend-web:latest .

# Push to Lightsail
aws lightsail push-container-image \
    --service-name crops-backend \
    --label web \
    --image crops-backend-web:latest

```

### 3. Deploy Configuration

```bash
aws lightsail create-container-service-deployment \
    --service-name crops-backend \
    --cli-input-json file://lightsail-containers.json
```

## Configuration Files

### Dockerfile
- Multi-stage build for optimization
- Non-root user for security
- Health checks included

### containers.json
- Container definitions for web and chancy worker
- Environment variable mapping
- Health check configuration
- Load balancer settings

### settings_production.py
- Production-optimized Django settings
- Security enhancements
- PostgreSQL database configuration
- Redis caching configuration

## Environment Variables

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `SECRET_KEY` | Django secret key | `your-secret-key` |
| `DATABASE_URL` | PostgreSQL connection string | `postgres://user:pass@host:5432/db` |
| `REDIS_URL` | Redis connection string | `redis://host:6379/0` |
| `ALLOWED_HOSTS` | Allowed host domains | `your-domain.com,*.amazonaws.com` |
| `AWS_ACCESS_KEY_ID` | AWS access key | `AKIA...` |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key | `...` |
| `AWS_STORAGE_BUCKET_NAME` | S3 bucket for media files | `crops-input` |
| `AWS_S3_CUSTOM_DOMAIN` | CloudFront domain | `d123.cloudfront.net` |

### Optional Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DEBUG` | Django debug mode | `False` |
| `CORS_ALLOWED_ORIGINS` | Frontend domains for CORS | `[]` |
| `FRONTEND_URL` | Frontend application URL | `""` |
| `SECURE_SSL_REDIRECT` | Force HTTPS redirect | `True` |

## Monitoring and Logs

### View Logs

```bash
# View all logs
aws lightsail get-container-log \
    --service-name crops-backend \
    --container-name web

```

### Health Checks

The deployment includes:
- **Application health check**: `/admin/login/` endpoint
- **Container health checks**: Built into Docker images
- **Database health check**: Via Django health check framework

### Monitoring Metrics

Access metrics in AWS Console:
- Container CPU/Memory usage
- Request count and response times
- Error rates

## Scaling

### Horizontal Scaling

```bash
# Scale to 3 instances
aws lightsail update-container-service \
    --service-name crops-backend \
    --scale 3
```

### Vertical Scaling

```bash
# Upgrade to medium power
aws lightsail update-container-service \
    --service-name crops-backend \
    --power medium
```

## Zero-Downtime Deployments

Lightsail Containers provides zero-downtime deployments through:

1. **Rolling Updates**: New containers are started before old ones are terminated
2. **Health Checks**: Ensures new containers are healthy before routing traffic
3. **Load Balancing**: Built-in load balancer distributes traffic
4. **Gradual Traffic Shift**: Traffic is gradually shifted to new containers

### Deployment Process

1. New container images are built and pushed
2. New deployment is created with updated images
3. New containers are started and health-checked
4. Traffic is gradually shifted to new containers
5. Old containers are terminated after successful deployment

## Database Migrations

### Automatic Migrations (Recommended)

Migrations are **automatically handled** during deployment via the `containers.json` configuration:

1. **Django migrations**: `python manage.py migrate --noinput`
2. **Chancy migrations**: `PYTHONPATH=/app chancy --app crops.chancy_worker.chancy_app misc migrate`
3. **Web server starts**: Only after migrations succeed

This ensures:
- ✅ Database schema is always up-to-date
- ✅ Chancy job tables are created/updated
- ✅ Zero-downtime deployments
- ✅ Automatic rollback if migrations fail

### Manual Migration (If Needed)

If you need to run migrations separately:

```bash
# Django migrations only
docker compose exec web python manage.py migrate

# Chancy migrations only
docker compose exec web bash -c "PYTHONPATH=/app chancy --app crops.chancy_worker.chancy_app misc migrate"

# Both migrations
docker compose exec web bash -c "python manage.py migrate && PYTHONPATH=/app chancy --app crops.chancy_worker.chancy_app misc migrate"
```

### Production Migration Command

For production containers:

```bash
# View migration logs
aws lightsail get-container-log \
    --service-name crops-backend \
    --container-name web \
    --region us-east-2 \
    --filter-pattern "migrate"
```

## Troubleshooting

### Common Issues

1. **Container fails to start**
   - Check environment variables
   - Verify database connectivity
   - Review container logs

2. **Database connection errors**
   - Ensure RDS security group allows connections
   - Verify DATABASE_URL format
   - Check RDS status

3. **Redis connection issues**
   - Verify ElastiCache cluster status
   - Check Redis URL format
   - Ensure security group access

4. **Static files not loading**
   - Verify S3 bucket permissions
   - Check CloudFront distribution
   - Confirm AWS credentials

5. **Chancy jobs not processing**
   - Check if Chancy worker container is running
   - Verify `chancy_jobs` table exists in database
   - Check worker logs for errors
   - Ensure `PYTHONPATH=/app` is set in worker command

6. **Chancy migration failures**
   - Check database connectivity
   - Verify Django app is properly configured with `chancy.contrib.django`
   - Ensure worker module can import Django models

### Log Analysis

```bash
# Check deployment status
aws lightsail get-container-service-deployments \
    --service-name crops-backend

# View specific container logs
aws lightsail get-container-log \
    --service-name crops-backend \
    --container-name web \
    --filter-pattern "ERROR"

# View Chancy worker logs
aws lightsail get-container-log \
    --service-name crops-backend \
    --container-name worker \
    --filter-pattern "chancy"

# Check migration status
aws lightsail get-container-log \
    --service-name crops-backend \
    --container-name web \
    --filter-pattern "migrate"
```

## Security Considerations

### Network Security
- RDS and ElastiCache in private subnets
- Security groups restrict access
- SSL/TLS encryption in transit

### Application Security
- Non-root container users
- Environment variable secrets
- CSRF and CORS protection
- Security headers configured

### Data Security
- RDS encryption at rest
- S3 bucket policies
- IAM role-based access

## Cost Optimization

### Container Service Costs
- **Small (1 vCPU, 512MB)**: ~$7/month
- **Medium (2 vCPU, 1GB)**: ~$20/month
- **Large (4 vCPU, 2GB)**: ~$40/month

### RDS Costs
- **db.t3.micro**: ~$13/month
- **db.t3.small**: ~$26/month

### ElastiCache Costs
- **cache.t3.micro**: ~$12/month

### Total Estimated Cost
- **Development**: ~$32/month
- **Production**: ~$58/month (with backups and multi-AZ)

## Backup and Recovery

### Database Backups
- Automated daily backups (7-day retention)
- Point-in-time recovery available
- Manual snapshots for major deployments

### Application Backups
- Container images stored in registry
- Environment configurations in version control
- S3 data replicated across regions

## Support and Maintenance

### Regular Maintenance Tasks
1. **Weekly**: Review logs and metrics
2. **Monthly**: Update dependencies and security patches
3. **Quarterly**: Review and optimize costs
4. **Annually**: Security audit and performance review

### Getting Help
- AWS Support (if enabled)
- AWS Lightsail Documentation
- Django Community Forums
- Project-specific issues: Create GitHub issue