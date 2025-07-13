#!/usr/bin/env python3
"""
Proxy configuration file for Instagram Reel Downloader
Configure your Indian proxy servers here
"""

import os

# Example Indian proxy servers
# Replace these with your actual working proxy servers
INDIAN_PROXY_SERVERS = [
    # Mumbai proxies
    'http://proxy1.mumbai.example.com:8080',
    'http://proxy2.mumbai.example.com:3128',
    'socks5://proxy3.mumbai.example.com:1080',
    
    # Delhi proxies
    'http://proxy1.delhi.example.com:8080',
    'http://proxy2.delhi.example.com:3128',
    'socks5://proxy3.delhi.example.com:1080',
    
    # Bangalore proxies
    'http://proxy1.bangalore.example.com:8080',
    'http://proxy2.bangalore.example.com:3128',
    
    # Chennai proxies
    'http://proxy1.chennai.example.com:8080',
    'http://proxy2.chennai.example.com:3128',
    
    # Kolkata proxies
    'http://proxy1.kolkata.example.com:8080',
    'http://proxy2.kolkata.example.com:3128',
    
    # Hyderabad proxies
    'http://proxy1.hyderabad.example.com:8080',
    'http://proxy2.hyderabad.example.com:3128'
]

# Free Indian proxy servers (these may not always be available)
FREE_INDIAN_PROXIES = [
    'http://103.87.169.177:56642',
    'http://103.87.169.185:56642',
    'http://103.87.169.186:56642',
    'http://103.87.169.183:56642',
    'http://103.87.169.190:56642',
    'http://103.87.169.200:56642',
    'http://103.87.169.210:56642',
    'http://103.87.169.220:56642'
]

# Configuration settings
PROXY_CONFIG = {
    'enabled': True,
    'primary_proxy': None,  # Will be set to first available proxy if None
    'fallback_proxies': INDIAN_PROXY_SERVERS + FREE_INDIAN_PROXIES,
    'rotation_enabled': True,
    'timeout': 20,
    'retries': 3
}

def get_proxy_config():
    """Get proxy configuration with environment variable overrides"""
    config = PROXY_CONFIG.copy()
    
    # Override with environment variables if set
    if os.getenv('PROXY_ENABLED'):
        config['enabled'] = os.getenv('PROXY_ENABLED').lower() == 'true'
    
    if os.getenv('PRIMARY_PROXY'):
        config['primary_proxy'] = os.getenv('PRIMARY_PROXY')
    
    if os.getenv('PROXY_LIST'):
        proxy_list = os.getenv('PROXY_LIST').split(',')
        config['fallback_proxies'] = [proxy.strip() for proxy in proxy_list]
    
    if os.getenv('PROXY_TIMEOUT'):
        config['timeout'] = int(os.getenv('PROXY_TIMEOUT'))
    
    if os.getenv('PROXY_RETRIES'):
        config['retries'] = int(os.getenv('PROXY_RETRIES'))
    
    return config

def test_proxy_connectivity():
    """Test connectivity to configured proxies"""
    import requests
    
    config = get_proxy_config()
    working_proxies = []
    
    for proxy in config['fallback_proxies']:
        try:
            proxies = {
                'http': proxy,
                'https': proxy
            }
            
            response = requests.get(
                'https://httpbin.org/ip',
                proxies=proxies,
                timeout=10
            )
            
            if response.status_code == 200:
                working_proxies.append(proxy)
                print(f"✓ {proxy} - Working")
            else:
                print(f"✗ {proxy} - Failed (Status: {response.status_code})")
                
        except Exception as e:
            print(f"✗ {proxy} - Failed ({str(e)})")
    
    print(f"\nWorking proxies: {len(working_proxies)}/{len(config['fallback_proxies'])}")
    return working_proxies

if __name__ == '__main__':
    print("Testing proxy connectivity...")
    test_proxy_connectivity()