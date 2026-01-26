#!/usr/bin/env python3
"""
Gumroad Product Publisher - Browser automation for publishing digital products.

Usage:
    python gumroad_publisher.py publish <product_dir>
    python gumroad_publisher.py list
    python gumroad_publisher.py login-test

Credentials are fetched from AWS SSM Parameter Store.
"""

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from datetime import datetime

# Playwright imports
try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("Error: playwright not installed. Run: pip install playwright && playwright install chromium")
    sys.exit(1)


def get_credential(key: str) -> str:
    """Fetch a credential from AWS SSM Parameter Store."""
    # Map key names to SSM parameter names
    ssm_map = {
        'GUMROAD_EMAIL': '/auto-dev/gumroad/email',
        'GUMROAD_PASSWORD': '/auto-dev/gumroad/password'
    }
    
    ssm_name = ssm_map.get(key, f'/auto-dev/gumroad/{key.lower()}')
    
    try:
        result = subprocess.run(
            [
                'aws', 'ssm', 'get-parameter',
                '--name', ssm_name,
                '--with-decryption',
                '--query', 'Parameter.Value',
                '--output', 'text',
                '--region', 'us-east-1'
            ],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error fetching credential {key} from SSM: {e.stderr}")
        raise ValueError(f"Could not find credential in SSM: {ssm_name}")


def parse_gumroad_listing(listing_path: Path) -> dict:
    """Parse GUMROAD_LISTING.md file into structured data."""
    content = listing_path.read_text()
    
    result = {
        'title': '',
        'subtitle': '',
        'price': '',
        'description': '',
        'tags': []
    }
    
    # Extract title
    title_match = re.search(r'^## Title\s*\n(.+?)(?=\n## |\Z)', content, re.MULTILINE | re.DOTALL)
    if title_match:
        result['title'] = title_match.group(1).strip().split('\n')[0]
    
    # Extract subtitle
    subtitle_match = re.search(r'^## Subtitle\s*\n(.+?)(?=\n## |\Z)', content, re.MULTILINE | re.DOTALL)
    if subtitle_match:
        result['subtitle'] = subtitle_match.group(1).strip().split('\n')[0]
    
    # Extract price
    price_match = re.search(r'^## Price\s*\n\$?(\d+)', content, re.MULTILINE)
    if price_match:
        result['price'] = price_match.group(1)
    
    # Extract description
    desc_match = re.search(r'^## Description\s*\n(.+?)(?=\n## |\Z)', content, re.MULTILINE | re.DOTALL)
    if desc_match:
        result['description'] = desc_match.group(1).strip()
    
    # Extract tags
    tags_match = re.search(r'^## Tags\s*\n(.+?)(?=\n## |\Z)', content, re.MULTILINE | re.DOTALL)
    if tags_match:
        tags_line = tags_match.group(1).strip().split('\n')[0]
        result['tags'] = [t.strip() for t in tags_line.split(',')]
    
    return result


class GumroadPublisher:
    """Browser automation for Gumroad product publishing."""
    
    def __init__(self):
        self.email = None
        self.password = None
        self.browser = None
        self.page = None
        
    async def load_credentials(self):
        """Load Gumroad credentials from secrets file or SSM."""
        print("Loading credentials...")
        self.email = get_credential('GUMROAD_EMAIL')
        self.password = get_credential('GUMROAD_PASSWORD')
        print(f"Loaded credentials for: {self.email}")
        
    async def start_browser(self, playwright, headless: bool = True):
        """Start browser instance."""
        print(f"Starting browser (headless={headless})...")
        self.browser = await playwright.chromium.launch(headless=headless)
        context = await self.browser.new_context()
        self.page = await context.new_page()
        
    async def close(self):
        """Close browser."""
        if self.browser:
            await self.browser.close()
            
    async def login(self) -> bool:
        """Login to Gumroad."""
        print("Navigating to Gumroad login...")
        await self.page.goto('https://gumroad.com/login')
        await self.page.wait_for_load_state('networkidle')
        
        # Fill email
        print("Entering credentials...")
        await self.page.fill('input[name="email"], input[type="email"]', self.email)
        await self.page.fill('input[name="password"], input[type="password"]', self.password)
        
        # Click login button
        await self.page.click('button[type="submit"], button:has-text("Log in")')
        
        # Wait for navigation
        try:
            await self.page.wait_for_url('**/dashboard**', timeout=15000)
            print("✅ Login successful!")
            return True
        except PlaywrightTimeout:
            # Check for error message
            error = await self.page.query_selector('.error, .alert-error, [role="alert"]')
            if error:
                error_text = await error.text_content()
                print(f"❌ Login failed: {error_text}")
            else:
                print("❌ Login failed: timeout waiting for dashboard")
            return False
            
    async def create_product(self, product_dir: Path) -> dict:
        """Create a new product on Gumroad."""
        # Find listing file
        listing_path = product_dir / 'GUMROAD_LISTING.md'
        if not listing_path.exists():
            listing_path = product_dir / 'SELL_THIS.md'
        if not listing_path.exists():
            raise FileNotFoundError(f"No GUMROAD_LISTING.md or SELL_THIS.md in {product_dir}")
            
        # Parse listing
        print(f"Parsing listing from {listing_path}...")
        listing = parse_gumroad_listing(listing_path)
        print(f"Product: {listing['title']} - ${listing['price']}")
        
        # Find product zip file
        zip_files = list(product_dir.glob('*.zip'))
        if not zip_files:
            # Create zip from directory
            import shutil
            zip_path = product_dir.parent / f"{product_dir.name}.zip"
            print(f"Creating zip file: {zip_path}")
            shutil.make_archive(str(zip_path.with_suffix('')), 'zip', product_dir)
            zip_file = zip_path
        else:
            zip_file = zip_files[0]
            
        print(f"Product file: {zip_file}")
        
        # Navigate to new product page
        print("Creating new product...")
        await self.page.goto('https://app.gumroad.com/products/new')
        await self.page.wait_for_load_state('networkidle')
        
        # Fill product name
        await self.page.fill('input[name="name"], input[placeholder*="name"]', listing['title'])
        
        # Fill price
        price_input = await self.page.query_selector('input[name="price"], input[placeholder*="price"]')
        if price_input:
            await price_input.fill(listing['price'])
            
        # Fill description
        desc_input = await self.page.query_selector('textarea[name="description"], [contenteditable="true"]')
        if desc_input:
            await desc_input.fill(listing['description'][:5000])  # Truncate if too long
            
        # Upload file
        file_input = await self.page.query_selector('input[type="file"]')
        if file_input:
            await file_input.set_input_files(str(zip_file))
            print("Uploading file...")
            await self.page.wait_for_timeout(5000)  # Wait for upload
            
        # Submit/Save
        submit_btn = await self.page.query_selector('button[type="submit"], button:has-text("Save"), button:has-text("Create")')
        if submit_btn:
            await submit_btn.click()
            await self.page.wait_for_load_state('networkidle')
            
        # Get product URL
        current_url = self.page.url
        print(f"✅ Product created: {current_url}")
        
        return {
            'success': True,
            'url': current_url,
            'title': listing['title'],
            'price': listing['price'],
            'created_at': datetime.utcnow().isoformat()
        }
        
    async def list_products(self) -> list:
        """List all products on Gumroad."""
        print("Fetching products list...")
        await self.page.goto('https://app.gumroad.com/products')
        await self.page.wait_for_load_state('networkidle')
        
        # Extract product info
        products = []
        product_cards = await self.page.query_selector_all('[data-product], .product-card, article')
        
        for card in product_cards:
            name_el = await card.query_selector('h2, h3, .product-name')
            name = await name_el.text_content() if name_el else 'Unknown'
            
            price_el = await card.query_selector('.price, [data-price]')
            price = await price_el.text_content() if price_el else '$0'
            
            products.append({
                'name': name.strip(),
                'price': price.strip()
            })
            
        return products


async def main():
    parser = argparse.ArgumentParser(description='Gumroad Product Publisher')
    subparsers = parser.add_subparsers(dest='command', required=True)
    
    # Publish command
    publish_parser = subparsers.add_parser('publish', help='Publish a product')
    publish_parser.add_argument('product_dir', help='Path to product directory')
    publish_parser.add_argument('--headless', action='store_true', default=True,
                               help='Run browser in headless mode')
    
    # List command
    subparsers.add_parser('list', help='List all products')
    
    # Login test command
    subparsers.add_parser('login-test', help='Test login credentials')
    
    args = parser.parse_args()
    
    async with async_playwright() as playwright:
        publisher = GumroadPublisher()
        
        try:
            await publisher.load_credentials()
            await publisher.start_browser(playwright, headless=getattr(args, 'headless', True))
            
            if not await publisher.login():
                print("Failed to login. Check credentials.")
                sys.exit(1)
                
            if args.command == 'publish':
                product_dir = Path(args.product_dir)
                if not product_dir.exists():
                    print(f"Product directory not found: {product_dir}")
                    sys.exit(1)
                    
                result = await publisher.create_product(product_dir)
                print(json.dumps(result, indent=2))
                
            elif args.command == 'list':
                products = await publisher.list_products()
                print(json.dumps(products, indent=2))
                
            elif args.command == 'login-test':
                print("Login test successful!")
                
        finally:
            await publisher.close()


if __name__ == '__main__':
    asyncio.run(main())

