def analyze_image_context(image_url: str, claimed_context: str, vision_web_detection_results: dict) -> dict:
    """
    Analyze whether the image is being used out of context compared to its verified web history.
    Returns a dictionary with keys: verdict, confidence, explanation, discrepancies.
    """
    # For this wrapper, we will use the claimed_context and vision_web_detection_results to build a prompt,
    # and pass the image_url as the image to the model (download image bytes).
    import requests
    from vertexai.generative_models import Part
    # Download image bytes
    try:
        resp = requests.get(image_url, timeout=15)
        resp.raise_for_status()
        image_bytes = resp.content
    except Exception as e:
        return {
            "verdict": "error",
            "confidence": 0.0,
            "explanation": f"Failed to download image: {e}",
            "discrepancies": [str(e)]
        }
    # Build prompt
    context_json = json.dumps(vision_web_detection_results, indent=2)
    prompt = f"""You are an image forensics analyst. Here is the context in which an image is being used (the 'claimed context'):\n\n{claimed_context}\n\nHere is the verified web context for this image (from Google Cloud Vision):\n\n{context_json}\n\nBased on both the image and the context, answer the following:\n\n1. Is the image being used in a way that matches its verified web history, or is it out of context?\n2. Give a confidence score (1 to 10).\n3. Explain your reasoning.\n4. List any specific discrepancies between the claimed context and the verified context.\n\nRespond in JSON with keys: verdict (match/mismatch), confidence (int), explanation (str), discrepancies (list of str)."""
    image_part = Part.from_data(data=image_bytes, mime_type="image/jpeg")
    response = model.generate_content([prompt, image_part])
    text = getattr(response, "text", None)
    if not text:
        return {
            "verdict": "error",
            "confidence": 0.0,
            "explanation": "No response from Gemini model.",
            "discrepancies": ["No output"]
        }
    # Try to parse JSON from model output
    try:
        import json as _json
        # Sometimes model output is not pure JSON, so extract JSON block
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            parsed = _json.loads(match.group(0))
        else:
            parsed = _json.loads(text)
        # Ensure required keys
        for key in ["verdict", "confidence", "explanation", "discrepancies"]:
            if key not in parsed:
                parsed[key] = None
        return parsed
    except Exception as e:
        return {
            "verdict": "error",
            "confidence": 0.0,
            "explanation": f"Failed to parse model output: {e}\nRaw output: {text}",
            "discrepancies": [str(e)]
        }
    
import os
import re
import json
import sys
import vertexai
from dotenv import load_dotenv
from google.cloud import vision
from vertexai.generative_models import GenerativeModel
from vertexai.generative_models import Part

'''
PSEUDO CODE for detect_web function:
function detect_web(image_path):
    create a Vision client
    read the image file as bytes
    construct a Vision Image object from those bytes
    call web_detection on the client, passing the image
    check for errors in the response
    return response.web_detection
'''
def detect_web(image_path):
    client = vision.ImageAnnotatorClient() #create a Vision client
    
    with open(image_path, 'rb') as image_file:
        content = image_file.read() #read the image file as bytes
    
    image = vision.Image(content=content) #construct a Vision Image object from those bytes
    
    response = client.web_detection(image=image) #call web_detection on the client, passing the image
    
    if response.error.message:
        raise Exception(f'{response.error.message}') #check for errors in the response
    
    return response.web_detection   #return response.web_detection


def format_web_detection(web_detection):

    result = {
        "best_guess_labels": [],
        "web_entities": [],
        "full_matching_images": [],
        "partial_matching_images": [],
        "visually_similar_images": [],
        "pages_with_matching_images": []
    }

    for label in web_detection.best_guess_labels:
        result["best_guess_labels"].append(label.label)

    for entity in web_detection.web_entities:
        result["web_entities"].append({
            "description": entity.description,
            "score": entity.score
        })
    for image in web_detection.full_matching_images:
        result["full_matching_images"].append({
            "url": image.url
        })
    for image in web_detection.partial_matching_images:
        result["partial_matching_images"].append({
            "url": image.url
        })
    for image in web_detection.visually_similar_images:
        result["visually_similar_images"].append(image.url)
    for page in web_detection.pages_with_matching_images:
        result["pages_with_matching_images"].append({
            "url": page.url,
            "title": page.page_title
        })
    return result

def build_prompt(web_detection_data):
    web_json = json.dumps(web_detection_data, indent=2)
    prompt = f"""You are an image forensics analyst. You have both the image pixels and the results of a Google
    Cloud Vision web detection scan. Use both the image and the metadata in your analysis.

    Here are the web detection results:
    {web_json}

    Based on both the image and the web detection metadata, provide the following analysis:

    1. **Inferred Image Content**: Infer what the image is likely about using best-guess labels,
    web entities, matching context, and the image itself. Clearly keep this inference grounded in both metadata and visual evidence.

    2. **Identification**: Identify likely people, places, objects, logos, artwork, or events
    referenced by the metadata or visible in the image. Be as specific as possible.

    3. **Origin & Source**: Based on the matching pages, URLs, and the image content, where did this image 
    likely originate? Is it a news photo, stock image, social media post, meme, 
    promotional material, or something else?

    4. **Internet Presence**: Summarize where this image appears online. Are there 
    patterns in the types of sites hosting it? Has it spread widely or is it relatively 
    obscure?

    5. **Key Takeaway**: In one or two sentences, give the most important thing someone 
    should know about this image.

    If the web detection results are mostly empty, or the image is unclear, note that the image appears to have 
    limited or no public internet presence and explain that confidence is limited because
    only limited data is available.

    Also, keep responses to one paragraph. Don't hedge unnecessarily. """
    return prompt

load_dotenv()

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
LOCATION = os.getenv("LOCATION", "us-central1")

vertexai.init(project=PROJECT_ID, location=LOCATION)
model = GenerativeModel("gemini-2.5-pro")



def generate_analysis(web_detection_data, image_path):
    prompt = build_prompt(web_detection_data)
    # Read image bytes
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    image_part = Part.from_data(data=image_bytes, mime_type="image/jpeg")
    # Send both prompt and image to the model
    response = model.generate_content([prompt, image_part])
    candidates = getattr(response, "candidates", None)
    if not candidates:
        return "Analysis could not be generated."

    if any(getattr(candidate, "blocked", False) for candidate in candidates):
        return "Analysis could not be generated."

    text = getattr(response, "text", None)
    if not text:
        return "Analysis could not be generated."
    return text


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py <image_path>")
        sys.exit(1)

    image_path = sys.argv[1]
    web_detection = detect_web(image_path)
    formatted_web_detection = format_web_detection(web_detection)
    analysis = generate_analysis(formatted_web_detection, image_path)
    print(analysis)


if __name__ == "__main__":
    main()
