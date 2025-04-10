import os
import re
import logging
import requests
import json # Import json for potentially pretty-printing details

logger = logging.getLogger(__name__)
# Configure basic logging if not already configured elsewhere
# logging.basicConfig(level=logging.INFO)

def process_image_with_mathpix(image_data):
    """
    Process image data with Mathpix API to extract mathematical content, tables,
    chemical diagrams, and geometric figures. Returns a more detailed result.

    Args:
        image_data (str): Base64-encoded image data (can include data URI prefix)

    Returns:
        dict: Structured result containing extracted data and a detailed summary.
              Returns {"error": "message"} on failure.
    """
    # Get API keys from environment variables
    MATHPIX_APP_ID = os.getenv('MATHPIX_APP_ID')
    MATHPIX_APP_KEY = os.getenv('MATHPIX_APP_KEY')

    if not MATHPIX_APP_ID or not MATHPIX_APP_KEY:
        logger.error("Mathpix API credentials not configured")
        # It's often better to raise an exception or return None/error dict
        return {"error": "Mathpix API credentials not configured"}

    headers = {
        "app_id": MATHPIX_APP_ID,
        "app_key": MATHPIX_APP_KEY,
        "Content-Type": "application/json"
    }

    try:
        # Clean base64 data: remove data URI prefix if present
        if isinstance(image_data, str) and "base64," in image_data:
            image_data = image_data.split("base64,")[1]

        # --- Enhanced Payload ---
        # Requesting more specific data types
        payload = {
            "src": f"data:image/jpeg;base64,{image_data}", # Assuming JPEG, adjust if needed
            "formats": ["text", "data", "html"], # Keep requesting base formats
            "data_options": {
                "include_asciimath": True,
                "include_latex": True,
                "include_mathml": True, # Added MathML for completeness
                "include_tsv": True,      # Explicitly request TSV for tables
                "include_table_html": True # Explicitly request HTML for tables
            },
            "include_geometry_data": True, # Keep requesting geometry
            "include_smiles": True,        # Explicitly request SMILES for chemistry
            "include_inchi": True          # Optionally request InChI as well
            # Add other options as needed, e.g., language detection, confidence thresholds
            # "alphabets_allowed": {"en": True},
            # "rm_spaces": True
        }

        # Send request to Mathpix
        url = "https://api.mathpix.com/v3/text"
        logger.info("Sending request to Mathpix API...")
        response = requests.post(url, headers=headers, json=payload, timeout=60) # Increased timeout
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

        result = response.json()
        logger.info("Received response from Mathpix API.")
        extracted_text = result.get("text", "") # Récupère le contenu du champ "text"
        logger.info(f"Texte brut extrait par Mathpix (champ 'text', longueur: {len(extracted_text)} caractères):")
        # Optionnel: Afficher le début du texte pour vérification (peut être très long)
        logger.debug(f"Début du texte brut extrait: {extracted_text[:1000]}...")

        # --- More Comprehensive Structuring ---
        structured_result = {
            "raw_text": result.get("text", ""), # Keep the original MMD text
            "raw_html": result.get("html", ""), # Store the HTML output
            "confidence": result.get("confidence"),
            "confidence_rate": result.get("confidence_rate"),
            "is_printed": result.get("is_printed"),
            "is_handwritten": result.get("is_handwritten"),
            "auto_rotate_confidence": result.get("auto_rotate_confidence"),
            "auto_rotate_degrees": result.get("auto_rotate_degrees"),
            "version": result.get("version"),
            "request_id": result.get("request_id"),
            "detected_alphabets": result.get("detected_alphabets"),
            "error": result.get("error"), # Pass along any API-level errors
            "error_info": result.get("error_info"),
            # Flags for quick checks
            "has_math": False,
            "has_table": False,
            "has_chemistry": False,
            "has_geometry": False,
            # Dictionary to hold detailed, structured data
            "details": {
                "math": [], # Store all math formats found
                "tables": [], # Store TSV and/or HTML table data
                "chemistry": [], # Store SMILES and potentially InChI
                "geometry": None, # Store raw geometry JSON
                "geometry_summary": "No geometric figures detected." # Keep readable summary
            }
        }

        # Process 'data' array for math and tables
        if "data" in result:
            for data_item in result["data"]:
                item_type = data_item.get("type")
                item_value = data_item.get("value")

                if item_type in ["latex", "asciimath", "mathml"]:
                    structured_result["has_math"] = True
                    structured_result["details"]["math"].append(data_item) # Store full item

                elif item_type in ["tsv", "table_html"]:
                    structured_result["has_table"] = True
                    structured_result["details"]["tables"].append(data_item) # Store full item

        # Process geometry data
        if "geometry_data" in result and result["geometry_data"]:
            structured_result["has_geometry"] = True
            # Store the raw geometry data
            structured_result["details"]["geometry"] = result["geometry_data"]
            # Generate the readable summary separately
            structured_result["details"]["geometry_summary"] = process_geometry_data(result["geometry_data"])

        # Process chemistry data (check raw text for SMILES tags)
        # Note: Mathpix might also return chemistry info differently in the future.
        # Checking the 'text' field is a robust way for now.
        if structured_result["raw_text"]:
            # Regex to find smiles tags and potentially capture attributes like inchi
            smiles_pattern = r'<smiles(?:\s+inchi="([^"]*)")?(?:\s+inchikey="([^"]*)")?.*?>(.*?)</smiles>'
            # findall returns tuples: (inchi, inchikey, smiles_string) - inchi/key might be None
            smiles_matches = re.findall(smiles_pattern, structured_result["raw_text"])

            if smiles_matches:
                structured_result["has_chemistry"] = True
                for inchi, inchikey, smiles_str in smiles_matches:
                    chem_detail = {"smiles": smiles_str}
                    if inchi:
                        chem_detail["inchi"] = inchi
                    if inchikey:
                        chem_detail["inchikey"] = inchikey
                    structured_result["details"]["chemistry"].append(chem_detail)

        # --- Generate the Enhanced Summary ---
        formatted_summary = format_mathpix_result_for_assistant(structured_result)
        structured_result["formatted_summary"] = formatted_summary # Add summary to the main result

        return structured_result

    except requests.exceptions.RequestException as e:
        logger.error(f"Network error calling Mathpix API: {str(e)}")
        return {"error": f"Network error: {str(e)}"}
    except json.JSONDecodeError as e:
         logger.error(f"Error decoding Mathpix API JSON response: {str(e)}")
         # Try to include response text if possible and not too large
         response_text = ""
         try:
             response_text = response.text[:500] # Limit size
         except Exception:
             pass # Ignore errors getting response text
         return {"error": f"JSON decode error: {str(e)} - Response text: {response_text}"}
    except Exception as e:
        logger.exception(f"Unexpected error processing image with Mathpix: {str(e)}") # Use logger.exception to include traceback
        return {"error": f"Unexpected error: {str(e)}"}

def format_mathpix_result_for_assistant(result):
    """
    Format Mathpix results into a more detailed text summary for the assistant.
    """
    summary = []

    # Add header based on detected content types
    content_types = []
    if result.get("has_math"): content_types.append("mathematical content")
    if result.get("has_table"): content_types.append("tables")
    if result.get("has_chemistry"): content_types.append("chemical formulas")
    if result.get("has_geometry"): content_types.append("geometric figures")

    if content_types:
        summary.append(f"Analysis complete. Image contains: {', '.join(content_types)}.")
    else:
        summary.append("Analysis complete. No specific STEM content types identified in the primary analysis.")

    # Add main extracted text (Mathpix Markdown)
    if result.get("raw_text"):
        summary.append("\n--- Extracted Content (Mathpix Markdown) ---")
        summary.append(result["raw_text"])
        summary.append("--- End of Extracted Content ---")
    else:
         summary.append("\nNo main text content extracted.")

    # Add detailed sections if data exists
    details_added = False

    # Math Details
    if result.get("has_math") and result["details"].get("math"):
        details_added = True
        summary.append("\n--- Mathematical Details ---")
        for item in result["details"]["math"]:
            summary.append(f"- Type: {item.get('type')}")
            # Truncate long values for summary display if needed
            value_preview = item.get('value', '')[:150] # Show first 150 chars
            if len(item.get('value', '')) > 150:
                 value_preview += "..."
            summary.append(f"  Value: {value_preview}")
        summary.append("--- End of Mathematical Details ---")

    # Table Details
    if result.get("has_table") and result["details"].get("tables"):
        details_added = True
        summary.append("\n--- Table Details ---")
        for item in result["details"]["tables"]:
            summary.append(f"- Type: {item.get('type')}")
            # Provide TSV directly, or indicate HTML is available
            if item.get('type') == 'tsv':
                 summary.append("  Data (TSV):")
                 # Add indentation for readability
                 tsv_lines = item.get('value', '').splitlines()
                 for line in tsv_lines:
                     summary.append(f"    {line}")
            elif item.get('type') == 'table_html':
                 summary.append("  Data: HTML format available in 'raw_html' or 'details'.") # Refer to structured data
            else:
                 summary.append(f"  Value: {item.get('value', '')[:200]}...") # Fallback preview
        summary.append("--- End of Table Details ---")

    # Geometry Details (Using the pre-formatted summary)
    if result.get("has_geometry") and result["details"].get("geometry_summary"):
        details_added = True
        summary.append("\n--- Geometric Figure Summary ---")
        summary.append(result["details"]["geometry_summary"])
        summary.append("--- End of Geometric Figure Summary ---")
        # Note: Raw JSON data is in result["details"]["geometry"] if needed

    # Chemistry Details
    if result.get("has_chemistry") and result["details"].get("chemistry"):
        details_added = True
        summary.append("\n--- Chemical Formula Details ---")
        for item in result["details"]["chemistry"]:
            chem_parts = [f"SMILES: {item.get('smiles', 'N/A')}"]
            if "inchi" in item:
                chem_parts.append(f"InChI: {item['inchi']}")
            if "inchikey" in item:
                 chem_parts.append(f"InChIKey: {item['inchikey']}")
            summary.append(f"- {' | '.join(chem_parts)}")
        summary.append("--- End of Chemical Formula Details ---")

    if not details_added and not result.get("raw_text"):
         summary.append("\nNo detailed structured data could be extracted or formatted.")

    # Add confidence info if available
    if result.get("confidence") is not None:
         summary.append(f"\nOverall Confidence: {result['confidence']:.4f}")
    if result.get("confidence_rate") is not None:
         summary.append(f"Confidence Rate: {result['confidence_rate']:.4f}")

    # Add error info if present
    if result.get("error"):
        summary.append(f"\n--- API Error Information ---")
        summary.append(f"Error: {result['error']}")
        if result.get("error_info"):
             try:
                 # Pretty print error_info if it's complex
                 error_info_str = json.dumps(result['error_info'], indent=2)
                 summary.append(f"Error Info:\n{error_info_str}")
             except Exception:
                 summary.append(f"Error Info: {result['error_info']}") # Fallback to string conversion
        summary.append(f"--- End of API Error Information ---")


    return "\n".join(summary)

def process_geometry_data(geometry_data):
    """
    Process geometric data into a readable string format for summaries.
    (This function remains largely the same as its purpose is summarization)
    """
    if not geometry_data:
        return "No geometric figures detected."

    result_parts = [] # Changed to list for easier appending

    for i, figure in enumerate(geometry_data):
        result_parts.append(f"\nFigure {i+1}:")
        shape_list = figure.get("shape_list", [])
        label_list = figure.get("label_list", [])

        if not shape_list and not label_list:
             result_parts.append("- No shapes or labels found for this figure.")
             continue

        # Process shapes
        if shape_list:
            result_parts.append("  Shapes:")
            for shape in shape_list:
                shape_type = shape.get("type", "unknown shape")
                result_parts.append(f"  - Type: {shape_type}")

                # Add specific details for known shapes like triangles
                if shape_type == "triangle":
                    vertices = shape.get("vertex_list", [])
                    result_parts.append(f"    - Vertices ({len(vertices)}):")
                    for j, vertex in enumerate(vertices):
                        vx = vertex.get('x', 'N/A')
                        vy = vertex.get('y', 'N/A')
                        result_parts.append(f"      * V{j+1}: ({vx}, {vy})")
                    # Could add edge info here if needed: vertex.get('edge_list')
                # Add elif for other shape types if supported in the future
        else:
             result_parts.append("  - No shapes detected for this figure.")


        # Process labels
        if label_list:
            result_parts.append("  Labels:")
            for label in label_list:
                label_text = label.get("text", "[no text]")
                # Clean up common MMD wrappers if present in label text for summary
                label_text = re.sub(r'^\\\( | \\?\)$', '', label_text).strip()
                label_text = re.sub(r'^\\\[ | \\?\]$', '', label_text).strip()

                position = label.get("position", {})
                pos_x = position.get('top_left_x', 'N/A')
                pos_y = position.get('top_left_y', 'N/A')
                pos_w = position.get('width', 'N/A')
                pos_h = position.get('height', 'N/A')
                result_parts.append(f"  - Text: \"{label_text}\"")
                result_parts.append(f"    Position (x,y): ({pos_x}, {pos_y}), Size (w,h): ({pos_w}, {pos_h})")
                # Add confidence if needed: label.get('confidence')
        else:
             result_parts.append("  - No labels detected for this figure.")


    # Join all parts skipping the initial newline if result_parts[0] starts with \n
    full_summary = "".join(result_parts)
    if full_summary.startswith("\n"):
         return full_summary[1:] # Remove leading newline
    return full_summary


# --- Example Usage (Optional: Requires setting environment variables) ---
if __name__ == '__main__':
    # This part will only run when the script is executed directly
    # For testing, you would need a base64 encoded image string.
    # Replace this with your actual base64 image data
    example_base64_image = "/9j/4AAQSkZJRgABAQEASABIAAD..." # A very short placeholder

    # Make sure to set your environment variables before running
    # export MATHPIX_APP_ID='your_app_id'
    # export MATHPIX_APP_KEY='your_app_key'

    if len(example_base64_image) < 50:
         print("Please replace 'example_base64_image' with actual base64 data for testing.")
    elif not os.getenv('MATHPIX_APP_ID') or not os.getenv('MATHPIX_APP_KEY'):
         print("Please set MATHPIX_APP_ID and MATHPIX_APP_KEY environment variables for testing.")
    else:
        print("Processing example image...")
        # Configure logging for example run
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        structured_data = process_image_with_mathpix(example_base64_image)

        print("\n--- Structured Result ---")
        # Use json.dumps for pretty printing the complex dictionary
        print(json.dumps(structured_data, indent=2))

        # The formatted summary is already inside structured_data['formatted_summary']
        print("\n--- Formatted Summary for Assistant ---")
        print(structured_data.get("formatted_summary", "No summary generated."))
