# Automated Database Migration Guide

This guide explains how to implement automated database migrations for your Django application deployed on AWS Lightsail Containers.

## 🚨 Problem with Manual Migrations

Your current manual migration process has these issues:
- **Security Risk**: Database must be publicly accessible during migrations
- **Human Error**: Manual steps prone to mistakes
- **No Rollback**: No automated way to revert failed migrations
- **Downtime**: Potential service interruption during migrations
- **Operational Overhead**: Requires manual intervention for every deployment

## ✅ Automated Solution: Migration Init Container

### How It Works

1. **Migration Container**: Runs `python manage.py migrate` before web container starts
2. **Dependency Chain**: Web container only starts after migrations complete successfully
3. **Private Database**: Database stays in private subnet, only accessible from containers
4. **Atomic Deployments**: Migrations are part of the deployment process
5. **Automatic Rollback**: Failed migrations prevent new deployment from going live

### Architecture

```
Deployment Pipeline:
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Build Image   │ -> │  Migration      │ -> │   Web Server    │
│                 │    │  Container      │    │   Container     │
│                 │    │  (runs migrate) │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                              │                        ^
                              v                        │
                       ┌─────────────────┐            │
                       │   RDS Database  │ <----------┘
                       │   (Private)     │
                       └─────────────────┘
```

## 🚀 Implementation

### 1. Updated Container Configuration

The new `containers-with-migrations.json` includes:

```json
{
  "containers": {
    "migrate": {
      "image": ":crops-backend.web.latest",
      "command": ["python", "manage.py", "migrate", "--noinput"]
    },
    "web": {
      "image": ":crops-backend.web.latest",
      "dependsOn": [{"containerName": "migrate", "condition": "SUCCESS"}]
    }
  }
}
```

### 2. Enhanced Deployment Script

Use `deploy-with-migrations.sh` instead of the original `deploy.sh`:

```bash
./deploy-with-migrations.sh
```

This script:
- Builds and pushes Docker images
- Applies environment variables to both containers
- Deploys with migration dependency
- Monitors deployment progress
- Provides helpful logging commands

### 3. Automatic Rollback

AWS Lightsail Containers automatically handles rollbacks:

- **Failed migrations** → Container fails to start → Auto-rollback to previous deployment
- **Application errors** → Health checks fail → Auto-rollback to previous deployment
- **No manual intervention needed** → Lightsail manages this automatically

⚠️ **Important**: Auto-rollback handles code deployment but doesn't reverse database migrations that already succeeded.

## 📊 Benefits vs. Manual Process

| Aspect | Manual Process | Automated Process |
|--------|----------------|-------------------|
| **Security** | ❌ DB must be public | ✅ DB stays private |
| **Reliability** | ❌ Human error prone | ✅ Consistent automation |
| **Rollback** | ❌ Manual intervention | ✅ Automatic via deployment |
| **Downtime** | ❌ Potential downtime | ✅ Zero-downtime with health checks |
| **Monitoring** | ❌ Limited visibility | ✅ Full deployment logs |
| **Scalability** | ❌ Doesn't scale | ✅ Works with multiple instances |

## 🔧 Migration Best Practices

### 1. Write Backward-Compatible Migrations

```python
# Good: Backward compatible
class Migration(migrations.Migration):
    operations = [
        migrations.AddField(
            model_name='user',
            name='new_field',
            field=models.CharField(max_length=100, null=True)  # Allow null initially
        ),
    ]

# Avoid: Breaking changes
class Migration(migrations.Migration):
    operations = [
        migrations.RemoveField('user', 'old_field'),  # Could break old code
    ]
```

### 2. Test Migrations Thoroughly

```bash
# Test migrations locally with production-like data
python manage.py migrate --plan
python manage.py migrate --check
```

### 3. Monitor Migration Performance

```bash
# Check migration logs
aws lightsail get-container-log \
    --service-name crops-backend \
    --container-name migrate \
    --region us-east-2 \
    --profile crops-deploy
```

## 🚨 Emergency Procedures

### Migration Failure Recovery

1. **Check Migration Logs**:
   ```bash
   aws lightsail get-container-log --service-name crops-backend --container-name web
   ```

2. **Identify Failed Migration**:
   ```bash
   # In your local environment
   python manage.py showmigrations --plan
   ```

3. **Recovery Process**:
   - **Automatic**: Lightsail reverts to previous deployment automatically
   - **Manual**: Fix migration locally and redeploy
   - **Database cleanup**: If migration partially succeeded, may need manual database fixes

### Database Backup Before Major Migrations

```bash
# Create RDS snapshot before major deployments
aws rds create-db-snapshot \
    --db-instance-identifier crops-backend-db \
    --db-snapshot-identifier crops-backup-$(date +%Y%m%d-%H%M%S)
```

## 📈 Advanced Configuration

### 1. Migration Timeout Configuration

Add timeout to prevent hanging migrations:

```json
{
  "migrate": {
    "command": ["timeout", "300", "python", "manage.py", "migrate", "--noinput"]
  }
}
```

### 2. Health Checks for Migration Container

```json
{
  "migrate": {
    "healthCheck": {
      "command": ["python", "manage.py", "check", "--database", "default"],
      "interval": 30,
      "timeout": 10,
      "retries": 3
    }
  }
}
```

### 3. Environment-Specific Migration Commands

```bash
# Development: Include test data
python manage.py migrate && python manage.py loaddata fixtures/dev_data.json

# Staging: Validate migrations
python manage.py migrate --check && python manage.py migrate

# Production: Conservative migrations
python manage.py migrate --verbosity=2 --noinput
```

## 🔍 Monitoring and Observability

### Key Metrics to Monitor

1. **Migration Duration**: Track how long migrations take
2. **Migration Success Rate**: Monitor failed deployments
3. **Database Connection Health**: Ensure DB connectivity
4. **Container Resource Usage**: Monitor migration container resource consumption

### Logging Strategy

```python
# In settings_production.py
LOGGING = {
    'loggers': {
        'django.db.migrations': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True,
        },
    },
}
```

## 🎯 Next Steps

1. **Test the new deployment process** in a staging environment first
2. **Create database backup** before first automated migration
3. **Monitor the first few deployments** closely
4. **Document any environment-specific considerations**
5. **Train team members** on the new deployment process

## 📞 Troubleshooting

### Common Issues

1. **Migration Container Fails to Start**
   - Check environment variables are properly set
   - Verify database connectivity
   - Review migration container logs

2. **Web Container Won't Start After Migration**
   - Check migration completed successfully
   - Verify database schema is consistent
   - Review web container logs

3. **Database Lock Issues**
   - Ensure no other processes are accessing database during migration
   - Check for long-running queries
   - Consider migration chunking for large data changes

### Getting Help

- **View deployment status**: `aws lightsail get-container-service-deployments --service-name crops-backend`
- **Check migration logs**: `aws lightsail get-container-log --service-name crops-backend --container-name migrate`
- **Monitor web container**: `aws lightsail get-container-log --service-name crops-backend --container-name web`
