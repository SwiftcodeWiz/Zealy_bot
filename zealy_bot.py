import hashlib
import asyncio
import re
import shutil
import time
import os
import traceback
import sys
from datetime import datetime
import platform
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, List
import threading
from queue import Queue, Empty
from collections import deque
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, List
import threading
from queue import Queue, Empty

# First check if required packages are installed
try:
    import psutil
    from dotenv import load_dotenv
    import chromedriver_autoinstaller
    from telegram import Update
    from telegram.ext import (
        Application,
        CommandHandler,
        ContextTypes,
        ApplicationHandlerStop,
        MessageHandler,
        filters
    )
    from telegram.error import TelegramError, NetworkError
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import (
        StaleElementReferenceException,
        WebDriverException,
        TimeoutException,
        NoSuchElementException
    )
    from selenium.webdriver.chrome.service import Service
except ImportError as e:
    print(f"ERROR: Missing required package: {str(e)}")
    print("Please install required packages using:")
    print("pip install python-telegram-bot selenium python-dotenv psutil chromedriver-autoinstaller")
    if not os.getenv('IS_RENDER', 'false').lower() == 'true':
        input("Press Enter to exit...")
    sys.exit(1)

# Try to load .env file
print("Loading environment variables...")
load_dotenv()

# Check if env variables exist
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID_STR = os.getenv('CHAT_ID')

if not TELEGRAM_BOT_TOKEN:
    print("ERROR: TELEGRAM_BOT_TOKEN environment variable is missing!")
    print("Create a .env file in the same directory with:")
    print("TELEGRAM_BOT_TOKEN=your_telegram_bot_token")
    print("CHAT_ID=your_chat_id")
    input("Press Enter to exit...")
    sys.exit(1)

if not CHAT_ID_STR:
    print("ERROR: CHAT_ID environment variable is missing!")
    print("Create a .env file in the same directory with:")
    print("CHAT_ID=your_chat_id (must be a number)")
    input("Press Enter to exit...")
    sys.exit(1)

# Parse CHAT_ID
try:
    CHAT_ID = int(CHAT_ID_STR)
except ValueError:
    print(f"ERROR: CHAT_ID must be an integer, got: {CHAT_ID_STR}")
    input("Press Enter to exit...")
    sys.exit(1)

# Chrome setup
print("🔧 Setting up Chrome...")
try:
    if not IS_RENDER:
        chromedriver_autoinstaller.install()
        print("✅ ChromeDriver installed")
except Exception as e:
    print(f"⚠️ ChromeDriver auto-install warning: {e}")

# Configuration
CHECK_INTERVAL = 25
MAX_URLS = 20 
ZEALY_CONTAINER_SELECTOR = "div.flex.flex-col.w-full.pt-100"
REQUEST_TIMEOUT = 30

# Set appropriate paths based on environment
IS_RENDER = os.getenv('IS_RENDER', 'false').lower() == 'true'

if IS_RENDER:
    CHROME_PATH = '/usr/bin/chromium'
    CHROMEDRIVER_PATH = '/usr/bin/chromedriver'
elif platform.system() == "Windows":
    # Default Windows paths
    CHROME_PATH = os.getenv('CHROME_BIN', 
                          r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    
    CHROMEDRIVER_PATH = os.getenv('CHROME_DRIVER', 
                                shutil.which('chromedriver') or r"C:\Program Files\chromedriver\chromedriver.exe")
else:
    # Linux/Docker paths
    CHROME_PATH = os.getenv('CHROME_BIN', '/usr/bin/chromium')
    CHROMEDRIVER_PATH = os.getenv('CHROME_DRIVER', '/usr/lib/chromium/chromedriver')

# Global storage
monitored_urls = {}
is_monitoring = False
SECURITY_LOG = "activity.log"

def kill_previous_instances():
    """Kill any previous bot instances"""
    current_pid = os.getpid()
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if 'python' in proc.info['name'].lower():
                    cmdline = ' '.join(proc.info['cmdline'])
                    if 'zealy' in cmdline.lower() and proc.info['pid'] != current_pid:
                        print(f"🚨 Killing previous instance (PID: {proc.info['pid']})")
                        proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                continue
    except Exception as e:
        print(f"Warning: Error checking previous instances: {e}")

def get_chrome_options():
    """Get optimized Chrome options"""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-features=VizDisplayCompositor")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-plugins")
    options.add_argument("--disable-images")
    options.add_argument("--disable-javascript")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # Add special options for Render.com
    if IS_RENDER:
        # Render-specific settings (more conservative)
        options.add_argument("--disable-setuid-sandbox")
        options.add_argument("--disable-dev-tools")
        options.add_argument("--no-zygote")
        options.add_argument("--single-process")
        options.add_argument("--memory-pressure-off")
        options.add_argument("--max_old_space_size=4096")
    
    # Use environment variables for paths
    print(f"🕵️ Using Chrome binary path: {CHROME_PATH}")
    print(f"🕵️ Using Chromedriver path: {CHROMEDRIVER_PATH}")
    
    # Check if we're in local development and paths should exist
    if not IS_RENDER:
        if not os.path.exists(CHROME_PATH):
            print(f"⚠️ WARNING: Chrome not found at expected path: {CHROME_PATH}")
            # Try to locate Chrome/Chromium
            if platform.system() == "Windows":
                possible_paths = [
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
                ]
                for path in possible_paths:
                    if os.path.exists(path):
                        print(f"✅ Found Chrome at: {path}")
                        options.binary_location = path
                        break
        else:
            options.binary_location = CHROME_PATH
    else:
        # On Render, we trust the paths exist
        options.binary_location = CHROME_PATH
        
    return options

def get_content_hash(url):
    driver = None
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            print(f"🌐 Initializing driver for URL: {url} (Attempt {retry_count + 1}/{max_retries})")
            options = get_chrome_options()
            
            try:
                if IS_RENDER or not os.path.exists(CHROMEDRIVER_PATH):
                    # On Render or if we can't find chromedriver, let Selenium find it automatically
                    print("Using default ChromeDriver (auto-detection)")
                    driver = webdriver.Chrome(options=options)
                else:
                    # Use specified path when available
                    print(f"Using specified ChromeDriver path: {CHROMEDRIVER_PATH}")
                    service = Service(executable_path=CHROMEDRIVER_PATH)
                    driver = webdriver.Chrome(service=service, options=options)
                    
                print(f"🌐 Loading URL: {url}")
                driver.set_page_load_timeout(REQUEST_TIMEOUT)
                driver.get(url)
                
                print("⏳ Waiting for page elements...")
                # Try multiple selectors in case the page structure changes
                selectors_to_try = [
                    ZEALY_CONTAINER_SELECTOR,
                    "div[class*='flex'][class*='flex-col']",
                    "main",
                    "body"
                ]
                
                container = None
                for selector in selectors_to_try:
                    try:
                        container = WebDriverWait(driver, 15).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                        )
                        print(f"✅ Found element with selector: {selector}")
                        break
                    except TimeoutException:
                        print(f"⚠️ Selector {selector} not found, trying next...")
                        continue
                
                if not container:
                    print("❌ No suitable container found")
                    return None
                
                # Wait a bit more for content to load
                time.sleep(2)
                content = container.text
                
                if not content or len(content.strip()) < 10:
                    print(f"⚠️ Content too short or empty: {len(content)} chars")
                    if retry_count < max_retries - 1:
                        retry_count += 1
                        time.sleep(5)  # Wait before retry
                        continue
                    return None
                
                print(f"📄 Content retrieved, length: {len(content)} chars")
                clean_content = re.sub(
                    r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z|\d+ XP|\b[A-F0-9]{8}-(?:[A-F0-9]{4}-){3}[A-F0-9]{12}\b', 
                    '', 
                    content
                )
                content_hash = hashlib.sha256(clean_content.strip().encode()).hexdigest()
                print(f"🔢 Hash generated: {content_hash[:8]}...")
                return content_hash
                
            except TimeoutException:
                print(f"⚠️ Timeout waiting for page elements on {url}")
                if retry_count < max_retries - 1:
                    retry_count += 1
                    time.sleep(5)
                    continue
                return None
            except WebDriverException as e:
                print(f"⚠️ WebDriver error: {str(e)}")
                if retry_count < max_retries - 1:
                    retry_count += 1
                    time.sleep(5)
                    continue
                return None
        except Exception as e:
            print(f"❌ Content check error: {str(e)}")
            if retry_count < max_retries - 1:
                retry_count += 1
                time.sleep(5)
                continue
            return None
        finally:
            try:
                if driver:
                    print("🧹 Closing WebDriver")
                    driver.quit()
                    driver = None
            except Exception as e:
                print(f"⚠️ Error closing WebDriver: {str(e)}")
    
    return None

async def auth_middleware(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        await update.message.reply_text("🚫 Unauthorized access!")
        raise ApplicationHandlerStop

async def send_notification(bot, message):
    retries = 0
    backoff_delay = 1
    
    while retries < 3:
        try:
            await bot.send_message(chat_id=CHAT_ID, text=message)
            print(f"✅ Sent notification: {message[:50]}...")
            return True
        except (TelegramError, NetworkError) as e:
            print(f"📡 Network error: {str(e)} - Retry {retries+1}/3")
            retries += 1
            if retries < 3:
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2
    
    print(f"❌ Failed to send notification after 3 retries")
    return False

async def check_urls(bot):
    global monitored_urls
    current_time = time.time()
    
    if not monitored_urls:
        print("⚠️ No URLs to check")
        return
        
    for url in list(monitored_urls.keys()):
        print(f"🔍 Checking URL: {url}")
        try:
            start_time = time.time()
            current_hash = get_content_hash(url)
            
            if not current_hash:
                monitored_urls[url]['failures'] += 1
                print(f"⚠️ Failed to get hash for {url} - Failure #{monitored_urls[url]['failures']}")
                if monitored_urls[url]['failures'] > 5:  # Increased threshold
                    del monitored_urls[url]
                    await send_notification(bot, f"🔴 Removed from monitoring due to repeated failures: {url}")
                    print(f"🗑️ Removed {url} after 5 failures")
                continue
                
            # Reset failure count on successful check
            monitored_urls[url]['failures'] = 0
            if monitored_urls[url]['hash'] != current_hash:
                print(f"🔔 Change detected for {url}")
                if current_time - monitored_urls[url].get('last_notified', 0) > 300:
                    success = await send_notification(
                        bot, f"🚨 CHANGE DETECTED!\n{url}\nResponse time: {time.time()-start_time:.2f}s")
                    if success:
                        monitored_urls[url].update({
                            'last_notified': current_time,
                            'hash': current_hash,
                            'last_checked': current_time
                        })
                        print(f"✅ Notification sent for {url}")
                    else:
                        print(f"❌ Failed to send notification for {url}")
            else:
                print(f"✓ No changes for {url}")
            
            monitored_urls[url]['last_checked'] = current_time
        except Exception as e:
            print(f"⚠️ Error processing {url}: {str(e)}")
            
    print(f"✅ Checked {len(monitored_urls)} URLs")

# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 Memory-Optimized Zealy Monitoring Bot\n\n"
        "Commands:\n"
        "/add <url> - Add Zealy URL to monitor\n"
        "/remove <number> - Remove URL by number\n"
        "/list - Show monitored URLs\n"
        "/run - Start monitoring\n"
        "/stop - Stop monitoring\n"
        "/status - Show monitoring statistics\n"
        "/debug <number> - Debug URL content\n"
        "/purge - Remove all URLs\n"
        f"Max URLs: {MAX_URLS}"
    )

async def list_urls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not monitored_urls:
        await update.message.reply_text("📋 No URLs monitored")
        return
    message = ["📋 Monitored URLs:"] + [f"{idx}. {url}" for idx, url in enumerate(monitored_urls.keys(), 1)]
    await update.message.reply_text("\n".join(message)[:4000])

async def remove_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return
    
    if not monitored_urls:
        await update.message.reply_text("❌ No URLs to remove")
        return
        
    try:
        if not context.args or not context.args[0]:
            await update.message.reply_text("❌ Usage: /remove <number>\nUse /list to see URL numbers")
            return
            
        try:
            url_index = int(context.args[0]) - 1  # Convert to 0-based index
        except ValueError:
            await update.message.reply_text("❌ Please provide a valid number")
            return
            
        url_list = list(monitored_urls.keys())
        
        if url_index < 0 or url_index >= len(url_list):
            await update.message.reply_text(f"❌ Invalid number. Use a number between 1 and {len(url_list)}")
            return
        
        url_to_remove = url_list[url_index]
        del monitored_urls[url_to_remove]
        
        await update.message.reply_text(
            f"✅ Removed: {url_to_remove}\n📊 Now monitoring: {len(monitored_urls)}/{MAX_URLS}\n💾 Memory freed!"
        )
        print(f"🗑️ Manually removed URL: {url_to_remove}")
        
    except ValueError:
        await update.message.reply_text("❌ Please provide a valid number")
    except Exception as e:
        print(f"⚠️ Error in remove_url: {str(e)}")
        try:
            await update.message.reply_text(f"❌ Error removing URL: {str(e)}")
        except:
            print(f"❌ Could not send error message: {str(e)}")

async def add_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return
    
    if len(monitored_urls) >= MAX_URLS:
        await update.message.reply_text(f"❌ Maximum URLs limit ({MAX_URLS}) reached")
        return
    
    try:
        # Check if args exist
        if not context.args or not context.args[0]:
            await update.message.reply_text("❌ Usage: /add <zealy-url>")
            return
            
        url = context.args[0].lower()
        print(f"📥 Attempting to add URL: {url}")
        
        # Validate URL format
        if not re.match(r'^https://(www\.)?zealy\.io/cw/[\w/-]+$', url):
            await update.message.reply_text("❌ Invalid Zealy URL format")
            return
            
        # Check if already monitoring
        if url in monitored_urls:
            await update.message.reply_text("ℹ️ URL already monitored")
            return
            
        # Show processing message
        processing_msg = await update.message.reply_text("⏳ Verifying URL...")
        
        # Get initial hash in a separate thread or process
        try:
            loop = asyncio.get_event_loop()
            print(f"🔄 Getting initial hash for {url}")
            initial_hash = await loop.run_in_executor(None, get_content_hash, url)
            
            if not initial_hash:
                await processing_msg.edit_text("❌ Failed to verify URL content. Check console for details.")
                return
                
            # Add to monitored URLs
            monitored_urls[url] = {
                'hash': initial_hash,
                'last_notified': 0,
                'last_checked': time.time(),
                'failures': 0
            }
            
            print(f"✅ URL added successfully: {url}")
            await processing_msg.edit_text(
                f"✅ Added: {url}\n📊 Now monitoring: {len(monitored_urls)}/{MAX_URLS}"
            )
            
        except Exception as e:
            print(f"❌ Error while getting initial hash: {str(e)}")
            await processing_msg.edit_text(f"❌ Failed to add URL: {str(e)}")
            
    except IndexError:
        await update.message.reply_text("❌ Usage: /add <zealy-url>")
    except Exception as e:
        print(f"⚠️ Error in add_url: {str(e)}")
        await update.message.reply_text(f"❌ Internal server error: {str(e)}")

async def run_monitoring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_monitoring
    
    if is_monitoring:
        await update.message.reply_text("⚠️ Already monitoring")
        return
    
    if not monitored_urls:
        await update.message.reply_text("❌ No URLs to monitor")
        return
    
    try:
        is_monitoring = True
        # Create monitoring task
        monitor_task = asyncio.create_task(start_monitoring(context.application))
        # Store task in context for reference
        context.chat_data['monitor_task'] = monitor_task
        await update.message.reply_text("✅ Monitoring started!")
        print("✅ Monitoring task created and started")
    except Exception as e:
        is_monitoring = False
        await update.message.reply_text(f"❌ Failed to start monitoring: {str(e)}")
        print(f"❌ Error starting monitoring: {str(e)}")

async def stop_monitoring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_monitoring
    is_monitoring = False
    
    # Try to cancel the task if it exists
    if 'monitor_task' in context.chat_data:
        try:
            context.chat_data['monitor_task'].cancel()
            del context.chat_data['monitor_task']
            print("🛑 Monitoring task cancelled")
        except Exception as e:
            print(f"⚠️ Error cancelling task: {str(e)}")
    
    await update.message.reply_text("🛑 Memory-optimized monitoring stopped")

async def purge_urls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global monitored_urls
    count = len(monitored_urls)
    monitored_urls.clear()
    await update.message.reply_text("✅ All URLs purged!")

async def start_monitoring(bot):
    """Main monitoring loop"""
    global is_monitoring
    bot = application.bot
    await send_notification(bot, "🔔 Monitoring started!")
    print("🔍 Entering monitoring loop")
    
    while is_monitoring:
        try:
            print(f"🔄 Running sequential URL check cycle - {len(monitored_urls)} URLs")
            start_time = time.time()
            await check_urls(bot)
            elapsed = time.time() - start_time
            wait_time = max(CHECK_INTERVAL - elapsed, 2)
            print(f"✓ Sequential check complete in {elapsed:.2f}s, waiting {wait_time:.2f}s")
            
            await asyncio.sleep(wait_time)
            
        except asyncio.CancelledError:
            print("🚫 Monitoring task was cancelled")
            break
        except Exception as e:
            print(f"🚨 Monitoring error: {str(e)}")
            print(traceback.format_exc())
            # Add a shorter sleep on error to prevent rapid failure loops
            await asyncio.sleep(30)
    
    print("👋 Exiting memory-optimized monitoring loop")
    await send_notification(bot, "🔴 Memory-optimized monitoring stopped!", priority=True)

def main():
    """Main function"""
    try:
        global CHROME_PATH, CHROMEDRIVER_PATH, driver_pool
        
        print(f"🚀 Starting bot at {datetime.now()}")
        kill_previous_instances()

        # Debug environment info
        print(f"🌍 Operating System: {platform.system()}")
        print(f"🌍 Running on Render: {IS_RENDER}")
        print(f"💾 Chrome path: {CHROME_PATH}")
        print(f"💾 Chromedriver path: {CHROMEDRIVER_PATH}")
        
        if not IS_RENDER:
            print(f"📂 Chrome exists: {os.path.exists(CHROME_PATH)}")
            print(f"📂 Chromedriver exists: {os.path.exists(CHROMEDRIVER_PATH)}")
            
            # Try to find Chrome and Chromedriver if not at expected locations
            chrome_path_to_use = CHROME_PATH
            chromedriver_path_to_use = CHROMEDRIVER_PATH
            
            if not os.path.exists(chrome_path_to_use):
                if platform.system() == "Windows":
                    chrome_possible_paths = [
                        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
                    ]
                    for path in chrome_possible_paths:
                        if os.path.exists(path):
                            print(f"✅ Found Chrome at: {path}")
                            chrome_path_to_use = path
                            break
            
            # Try to find ChromeDriver if not at expected path
            if not os.path.exists(CHROMEDRIVER_PATH):
                chromedriver_in_path = shutil.which('chromedriver')
                if chromedriver_in_path:
                    print(f"✅ Found Chromedriver in PATH: {chromedriver_in_path}")
                    chromedriver_path_to_use = chromedriver_in_path
                    
            # Update global variables with found paths
            if chrome_path_to_use != CHROME_PATH or chromedriver_path_to_use != CHROMEDRIVER_PATH:
                CHROME_PATH = chrome_path_to_use
                CHROMEDRIVER_PATH = chromedriver_path_to_use
                print(f"📌 Using Chrome at: {CHROME_PATH}")
                print(f"📌 Using Chromedriver at: {CHROMEDRIVER_PATH}")
        
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        print("Creating Telegram application...")
        application = (
            Application.builder()
            .token(TELEGRAM_BOT_TOKEN)
            .concurrent_updates(True)
            .post_init(lambda app: app.bot.delete_webhook(drop_pending_updates=True))
            .build()
        )

        print("Adding handlers...")
        application.add_handler(MessageHandler(filters.ALL, auth_middleware), group=-1)
        
        # Add command handlers
        handlers = [
            CommandHandler("start", start),
            CommandHandler("add", add_url),
            CommandHandler("remove", remove_url),
            CommandHandler("list", list_urls),
            CommandHandler("run", run_monitoring),
            CommandHandler("stop", stop_monitoring),
            CommandHandler("purge", purge_urls)
        ]
        
        for handler in handlers:
            application.add_handler(handler)

        print("Starting polling...")
        application.run_polling()
    except KeyboardInterrupt:
        print("\n🛑 Graceful shutdown requested")
    except Exception as e:
        print(f"❌ CRITICAL ERROR: {str(e)}")
        print(traceback.format_exc())
        if not IS_RENDER:
            input("Press Enter to exit...")
    finally:
        try:
            executor.shutdown()
        except:
            pass
        print("🧹 Cleaning up...")

if __name__ == "__main__":
    print("Script starting...")
    try:
        main()
    except Exception as e:
        print(f"❌ CRITICAL ERROR in __main__: {str(e)}")
        print(traceback.format_exc())
        input("Press Enter to exit...")