import os
import sys
import re
import time
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from urllib.parse import urlparse, urljoin
from google.cloud import vision
from PIL import Image
from io import BytesIO
from dotenv import load_dotenv

# Import analyze_image_context from main.py
from main import analyze_image_context

load_dotenv()

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_HEADERS = {"User-Agent": USER_AGENT}
REQUEST_TIMEOUT = 15
MIN_IMAGE_DIM = 200

# Helper: Detect platform

def detect_platform(url):
    domain = (urlparse(url).netloc or "").lower()
    if "twitter.com" in domain or "x.com" in domain:
        return "twitter"
    return "article"

# Helper: Selenium driver

def get_selenium_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument(f"user-agent={USER_AGENT}")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(ChromeDriverManager().install(), options=options)
    driver.set_page_load_timeout(REQUEST_TIMEOUT)
    return driver

# Helper: Check image size (by attributes or download)

def is_large_image(img_tag, base_url):
    width = img_tag.get("width")
    height = img_tag.get("height")
    try:
        if width and height and int(width) >= MIN_IMAGE_DIM and int(height) >= MIN_IMAGE_DIM:
            return True
    except Exception:
        pass
    # Try to fetch and check size if not in attributes
    src = img_tag.get("src") or img_tag.get("data-src")
    if not src:
        return False
    img_url = urljoin(base_url, src)
    try:
        resp = requests.get(img_url, headers=REQUEST_HEADERS, timeout=5)
        img = Image.open(BytesIO(resp.content))
        if img.width >= MIN_IMAGE_DIM and img.height >= MIN_IMAGE_DIM:
            return True
    except Exception:
        pass
    return False

# Helper: Vision API

def get_vision_web_detection(image_url):
    client = vision.ImageAnnotatorClient()
    image = vision.Image()
    image.source.image_uri = image_url
    response = client.web_detection(image=image)
    if response.error.message:
        raise Exception(f"Vision API error: {response.error.message}")
    return response.web_detection

# Article scraping

def scrape_article(url):
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        # Try Selenium fallback
        try:
            driver = get_selenium_driver()
            driver.get(url)
            time.sleep(2)
            html = driver.page_source
            soup = BeautifulSoup(html, "html.parser")
            driver.quit()
        except Exception as e:
            return {"error": f"Failed to load page: {e}"}

    # Image extraction
    og_image = soup.find("meta", property="og:image")
    twitter_image = soup.find("meta", property="twitter:image")
    main_img_url = None
    if og_image and og_image.get("content"):
        main_img_url = urljoin(url, og_image["content"])
    elif twitter_image and twitter_image.get("content"):
        main_img_url = urljoin(url, twitter_image["content"])
    else:
        # Find first large <img> in <article> or main content
        article = soup.find("article") or soup.find("main") or soup
        for img in article.find_all("img"):
            if is_large_image(img, url):
                src = img.get("src") or img.get("data-src")
                if src:
                    main_img_url = urljoin(url, src)
                    break

    # Title extraction
    title = ""
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"]
    elif soup.title and soup.title.string:
        title = soup.title.string.strip()
    else:
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)

    # Caption/alt text
    caption = ""
    if main_img_url:
        img_tag = soup.find("img", src=re.compile(re.escape(main_img_url.split("?")[0])))
        if img_tag:
            caption = img_tag.get("alt") or img_tag.get("title") or ""

    # Body text extraction
    body_text = ""
    article_tag = soup.find("article")
    if article_tag:
        body_text = " ".join(p.get_text(" ", strip=True) for p in article_tag.find_all("p"))
    else:
        # Find largest text-containing <div>
        divs = soup.find_all("div")
        max_div = max(divs, key=lambda d: len(d.get_text(" ", strip=True)), default=None)
        if max_div:
            body_text = max_div.get_text(" ", strip=True)

    return {
        "image_urls": [main_img_url] if main_img_url else [],
        "headline": title,
        "caption": caption,
        "body_text": body_text,
    }

# Twitter/X scraping

def scrape_twitter(url):
    # Try Selenium first
    try:
        driver = get_selenium_driver()
        driver.get(url)
        time.sleep(2)
        tweet_text = ""
        image_urls = []
        # Tweet text
        tweet_div = driver.find_element(By.CSS_SELECTOR, '[data-testid="tweetText"]')
        tweet_text = tweet_div.text
        # Images
        img_tags = driver.find_elements(By.CSS_SELECTOR, 'img[src*="twimg.com/media"]')
        for img in img_tags:
            src = img.get_attribute("src")
            if src:
                image_urls.append(src)
        driver.quit()
        return {
            "image_urls": image_urls,
            "headline": "",
            "caption": "",
            "body_text": tweet_text,
        }
    except Exception:
        # Fallback to nitter.net
        nitter_url = re.sub(r"https?://(x|twitter)\.com", "https://nitter.net", url)
        try:
            resp = requests.get(nitter_url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            tweet_text = soup.find("div", {"class": "tweet-content"})
            tweet_text = tweet_text.get_text(" ", strip=True) if tweet_text else ""
            image_urls = []
            for img in soup.find_all("img", src=re.compile(r"/pic/media%2F")):
                src = img.get("src")
                if src:
                    image_urls.append(urljoin(nitter_url, src))
            return {
                "image_urls": image_urls,
                "headline": "",
                "caption": "",
                "body_text": tweet_text,
            }
        except Exception as e:
            return {"error": f"Failed to scrape tweet: {e}"}

# Main scrape function

def scrape_url(url):
    platform = detect_platform(url)
    if platform == "twitter":
        return scrape_twitter(url)
    else:
        return scrape_article(url)

# Full pipeline

def process_url(url):
    scrape_result = scrape_url(url)
    if "error" in scrape_result:
        return {"url": url, "error": scrape_result["error"]}
    results = []
    for img_url in scrape_result["image_urls"]:
        try:
            vision_results = get_vision_web_detection(img_url)
            # Aggregate context
            web_entities = sorted(
                [(e.description, e.score) for e in getattr(vision_results, "web_entities", []) if e.description],
                key=lambda x: -x[1]
            )
            pages = [
                {"url": p.url, "title": p.page_title}
                for p in getattr(vision_results, "pages_with_matching_images", [])
            ]
            context_summary = {
                "web_entities": web_entities,
                "pages": pages,
            }
            verdict = analyze_image_context(
                image_url=img_url,
                claimed_context=" ".join([
                    scrape_result.get("headline", ""),
                    scrape_result.get("caption", ""),
                    scrape_result.get("body_text", "")
                ]).strip(),
                vision_web_detection_results=context_summary
            )
            results.append({
                "image_url": img_url,
                "headline": scrape_result.get("headline", ""),
                "caption": scrape_result.get("caption", ""),
                "body_text": scrape_result.get("body_text", ""),
                "cloud_vision_context": context_summary,
                "gemini_verdict": verdict
            })
        except Exception as e:
            results.append({
                "image_url": img_url,
                "error": f"Vision or analysis error: {e}"
            })
    return {
        "url": url,
        "results": results
    }

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scraper.py <url>")
        sys.exit(1)
    url = sys.argv[1]
    output = process_url(url)
    import pprint
    pprint.pprint(output)
