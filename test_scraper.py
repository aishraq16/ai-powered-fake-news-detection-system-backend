import sys
from scraper import process_url

def test_scraper():
    test_urls = [ 
                 "https://www.independent.ie/irish-news/israels-irish-embassy-condemned-over-european-terror-propaganda-tweets/30464051.html"
        # Add your test URLs here
        # Example:
        # "https://www.bbc.com/news/world-us-canada-12345678",
        # "https://twitter.com/username/status/1234567890",
    ]
    for url in test_urls:
        print(f"\nTesting URL: {url}")
        result = process_url(url)
        if "error" in result:
            print(f"Error: {result['error']}")
            continue
        for img_result in result.get("results", []):
            print(f"Image URL: {img_result.get('image_url')}")
            print(f"Headline: {img_result.get('headline')}")
            print(f"Caption: {img_result.get('caption')}")
            body = img_result.get('body_text', '')
            print(f"Body Text (snippet): {body[:200]}{'...' if len(body) > 200 else ''}")
            verdict = img_result.get('gemini_verdict', {})
            print(f"Gemini Verdict: {verdict.get('verdict')}")
            print(f"Confidence: {verdict.get('confidence')}")
            print(f"Explanation: {verdict.get('explanation')}")
            print(f"Discrepancies: {verdict.get('discrepancies')}")

if __name__ == "__main__":
    test_scraper()
