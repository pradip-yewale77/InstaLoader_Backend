# Instagram Reel Downloader with Proxy Support - Usage Guide

## 🚀 Quick Start

### Method 1: Using Shell Script (Recommended)
```bash
# Start with default proxy configuration
./start_with_proxy.sh

# Start with specific proxy
./start_with_proxy.sh --proxy http://proxy-server:8080

# Start with proxy list
./start_with_proxy.sh --proxy-list "http://proxy1:8080,http://proxy2:3128"

# Start without proxy
./start_with_proxy.sh --no-proxy
```

### Method 2: Using Python Script
```bash
# Interactive setup
python3 run_with_proxy.py

# Direct run
python3 Backend.py
```

### Method 3: Using Environment Variables
```bash
# Set proxy configuration
export PROXY_ENABLED=true
export PRIMARY_PROXY=http://your-proxy-server:8080
export PROXY_LIST=http://proxy1:8080,http://proxy2:3128

# Run the application
python3 Backend.py
```

## 🔧 Configuration

### 1. Edit Proxy Configuration
Edit `proxy_config.py` to add your Indian proxy servers:

```python
INDIAN_PROXY_SERVERS = [
    'http://your-mumbai-proxy:8080',
    'http://your-delhi-proxy:3128',
    'socks5://your-bangalore-proxy:1080'
]
```

### 2. Environment Variables
| Variable | Description | Example |
|----------|-------------|---------|
| `PROXY_ENABLED` | Enable/disable proxy | `true` or `false` |
| `PRIMARY_PROXY` | Primary proxy server | `http://proxy:8080` |
| `PROXY_LIST` | Comma-separated proxy list | `http://p1:8080,http://p2:3128` |
| `PROXY_TIMEOUT` | Proxy timeout in seconds | `20` |
| `PROXY_RETRIES` | Number of retry attempts | `3` |

## 🧪 Testing

### Test Proxy Connectivity
```bash
# Test all configured proxies
python3 proxy_config.py

# Test the full application
python3 test_proxy.py

# Test with Instagram URL
python3 test_proxy.py https://www.instagram.com/reel/ABC123/
```

### Test API Endpoints
```bash
# Test health endpoint
curl http://localhost:5000/health

# Test proxy configuration
curl http://localhost:5000/proxy-config

# Test proxy connectivity
curl -X POST http://localhost:5000/test-proxy \
  -H "Content-Type: application/json" \
  -d '{"proxy_url": "http://your-proxy:8080"}'
```

## 📱 API Usage

### Download Instagram Reel
```bash
curl -X POST http://localhost:5000/download-reel \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.instagram.com/reel/ABC123/", "quality": "high"}' \
  -o reel.mp4
```

### Get Reel Thumbnail
```bash
curl -X POST http://localhost:5000/get-reel-thumbnail \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.instagram.com/reel/ABC123/"}'
```

### Get Reel Information
```bash
curl -X POST http://localhost:5000/get-reel-info \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.instagram.com/reel/ABC123/"}'
```

## 🐍 Python Usage

### Basic Usage
```python
import requests

# Download reel
response = requests.post('http://localhost:5000/download-reel', json={
    'url': 'https://www.instagram.com/reel/ABC123/',
    'quality': 'high'
})

with open('reel.mp4', 'wb') as f:
    f.write(response.content)
```

### With Proxy Management
```python
import requests

# Update proxy configuration
requests.post('http://localhost:5000/proxy-config', json={
    'enabled': True,
    'primary_proxy': 'http://new-proxy:8080'
})

# Test proxy
response = requests.post('http://localhost:5000/test-proxy', json={
    'proxy_url': 'http://new-proxy:8080'
})
print(response.json())
```

## 🌐 Server Deployment

### Local Server
```bash
# Development server
python3 run_with_proxy.py

# Production server with Gunicorn
PROXY_ENABLED=true gunicorn -w 4 -b 0.0.0.0:5000 Backend:app
```

### Docker Deployment
```bash
# Build image
docker build -t instagram-downloader .

# Run with proxy
docker run -p 5000:5000 \
  -e PROXY_ENABLED=true \
  -e PRIMARY_PROXY=http://proxy:8080 \
  instagram-downloader
```

## 🔒 Security & Best Practices

### Proxy Security
1. **Use HTTPS proxies** when available
2. **Avoid free proxies** for production
3. **Rotate proxy credentials** regularly
4. **Monitor proxy usage** and costs

### Rate Limiting
1. **Respect Instagram's limits**
2. **Use delays between requests**
3. **Implement exponential backoff**
4. **Monitor for IP blocking**

### Performance Optimization
1. **Use geographically close proxies**
2. **Test proxy speed regularly**
3. **Cache responses when possible**
4. **Monitor proxy health**

## 🐛 Troubleshooting

### Common Issues

#### Proxy Connection Failed
```bash
# Check proxy connectivity
python3 proxy_config.py

# Test specific proxy
curl -X POST http://localhost:5000/test-proxy \
  -H "Content-Type: application/json" \
  -d '{"proxy_url": "http://your-proxy:8080"}'
```

#### Instagram Rate Limiting
- Use residential proxies
- Implement request delays
- Rotate IP addresses frequently

#### Slow Download Speed
- Check proxy speed: `python3 proxy_config.py`
- Use closer proxy servers
- Reduce concurrent requests

### Debug Mode
```bash
# Enable debug logging
export FLASK_DEBUG=1
python3 Backend.py
```

## 📊 Monitoring

### Health Check
```bash
# Check application health
curl http://localhost:5000/health
```

### Proxy Statistics
```bash
# Get proxy configuration
curl http://localhost:5000/proxy-config
```

### Clear Cache
```bash
# Clear application cache
curl -X POST http://localhost:5000/clear-cache
```

## 🎯 Example Indian Proxy Providers

### Paid Providers (Recommended)
1. **Bright Data** - Premium residential proxies
2. **Smartproxy** - Good performance in India
3. **Oxylabs** - Enterprise-grade proxies
4. **ProxyMesh** - Reliable datacenter proxies

### Free Proxies (Testing Only)
- Use `python3 proxy_config.py` to test connectivity
- Replace example URLs with actual working proxies
- Not recommended for production use

## 🔧 Advanced Configuration

### Custom Proxy Rotation
```python
# In proxy_config.py
PROXY_CONFIG = {
    'enabled': True,
    'rotation_enabled': True,
    'rotation_interval': 300,  # 5 minutes
    'max_requests_per_proxy': 100
}
```

### Proxy Authentication
```python
# Format: http://username:password@proxy:port
AUTHENTICATED_PROXY = 'http://user:pass@proxy.example.com:8080'
```

### SOCKS5 Proxy Support
```bash
# Install pysocks for SOCKS5 support
pip3 install pysocks

# Use SOCKS5 proxy
export PRIMARY_PROXY=socks5://proxy.example.com:1080
```

## 📝 Log Files

### Application Logs
- Check console output for errors
- Enable debug mode for detailed logs
- Monitor proxy connection status

### Proxy Logs
- Monitor proxy provider dashboards
- Track bandwidth usage
- Monitor IP rotation frequency

---

## 🎉 You're All Set!

Your Instagram Reel Downloader with proxy support is now configured and ready to use. The application will:

✅ Automatically use configured proxies
✅ Failover to backup proxies if needed
✅ Rotate proxies for better performance
✅ Cache responses for efficiency
✅ Handle rate limiting gracefully

For support or issues, check the troubleshooting section or test individual components using the provided scripts.