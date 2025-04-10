import os
import re
import logging
import requests

logger = logging.getLogger(__name__)

def process_image_with_mathpix(image_data):
    """
    Process image data with Mathpix API to extract mathematical content, tables, 
    chemical diagrams, and geometric figures

    Args:
        image_data (str): Base64-encoded image data

    Returns:
        dict: Structured result containing all extracted data
    """
    # Get API keys from environment variables
    MATHPIX_APP_ID = os.getenv('MATHPIX_APP_ID')
    MATHPIX_APP_KEY = os.getenv('MATHPIX_APP_KEY')

    if not MATHPIX_APP_ID or not MATHPIX_APP_KEY:
        logger.error("Mathpix API credentials not configured")
        return {"error": "Mathpix API credentials not configured"}

    headers = {
        "app_id": MATHPIX_APP_ID,
        "app_key": MATHPIX_APP_KEY,
        "Content-Type": "application/json"
    }

    try:
        # Clean base64 data if needed
        if isinstance(image_data, str) and "base64," in image_data:
            image_data = image_data.split("base64,")[1]

        # Configuration complète pour extraire tous les détails
        payload = {
            "src": f"data:image/jpeg;base64,{image_data}",
            "formats": ["text", "data", "html"],
            "data_options": {
                "include_asciimath": True,
                "include_latex": True,
                "include_mathml": True,
                "include_svg": True
            },
            "include_geometry_data": True,
            "include_line_data": True,  # Récupérer des données sur la structure des lignes
            "include_word_data": True,  # Récupérer des données sur les mots individuels
            "include_table_data": True  # Récupérer des données complètes sur les tables
        }

        # Send request to Mathpix
        url = "https://api.mathpix.com/v3/text"
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()

        result = response.json()

        # Structure the response with all available data
        structured_result = {
            "text": result.get("text", ""),
            "html": result.get("html", ""),  # Include HTML for better formatting
            "has_math": False,
            "has_table": False,
            "has_chemistry": False,
            "has_geometry": False,
            "details": {},
            "raw_data": result  # Store the full raw response for complete data access
        }

        # Process mathematical data
        if "data" in result:
            for data_item in result["data"]:
                if data_item.get("type") in ["latex", "asciimath", "mathml", "svg"]:
                    structured_result["has_math"] = True
                    if "math_details" not in structured_result["details"]:
                        structured_result["details"]["math_details"] = []
                    structured_result["details"]["math_details"].append(data_item)

                # Process tables
                if data_item.get("type") in ["tsv", "table_html"]:
                    structured_result["has_table"] = True
                    if "table_details" not in structured_result["details"]:
                        structured_result["details"]["table_details"] = []
                    structured_result["details"]["table_details"].append(data_item)

        # Process geometric data
        if "geometry_data" in result and result["geometry_data"]:
            structured_result["has_geometry"] = True
            structured_result["details"]["geometry_details"] = process_geometry_data(result["geometry_data"])

        # Process line data if available
        if "line_data" in result and result["line_data"]:
            structured_result["details"]["line_data"] = result["line_data"]

        # Process word data if available
        if "word_data" in result and result["word_data"]:
            structured_result["details"]["word_data"] = result["word_data"]

        # Check for chemical formulas (SMILES)
        if "text" in result:
            smiles_pattern = r'<smiles.*?>(.*?)</smiles>'
            smiles_matches = re.findall(smiles_pattern, result["text"])

            if smiles_matches:
                structured_result["has_chemistry"] = True
                structured_result["details"]["chemistry_details"] = smiles_matches

        # Format complete summary for assistant
        formatted_summary = format_mathpix_result_for_assistant(structured_result)
        structured_result["formatted_summary"] = formatted_summary
        
        # Log the size of the data
        logger.debug(f"Structured result: {len(str(structured_result))} characters")
        logger.debug(f"Formatted summary: {len(formatted_summary)} characters")

        return structured_result

    except Exception as e:
        logger.error(f"Error processing image with Mathpix: {str(e)}")
        return {"error": f"Error processing image: {str(e)}"}

def format_mathpix_result_for_assistant(result):
    """
    Format Mathpix results into a complete, well-structured text for the assistant
    """
    try:
        # Log the entire result structure for debugging
        logger.debug(f"Formatting Mathpix result: {result.keys()}")
        if "raw_data" in result:
            logger.debug(f"Raw data fields: {result['raw_data'].keys()}")
            
        summary = []
        
        # Fallback: If we can't extract specific data, at least send the raw text
        if "raw_data" in result and "text" in result["raw_data"]:
            raw_text = result["raw_data"]["text"]
            logger.debug(f"Using raw_data.text as fallback: {len(raw_text)} characters")
            summary.append("Extracted content:")
            summary.append(raw_text)
            # Return early with at least the raw text
            return "\n".join(summary)

        # Continue with structured extraction if raw_data.text wasn't available
        
        # Add header based on content
        content_types = []
        if result.get("has_math", False): content_types.append("mathematical formulas")
        if result.get("has_table", False): content_types.append("tables")
        if result.get("has_chemistry", False): content_types.append("chemical formulas")
        if result.get("has_geometry", False): content_types.append("geometric figures")

        if content_types:
            summary.append(f"Image contains {', '.join(content_types)}.")

        # Add main text - This is the most important part containing the full transcription
        if result.get("text"):
            summary.append("\nExtracted content:")
            summary.append(result["text"])
        
        # If no content so far but we have HTML, use that
        if not summary and result.get("html"):
            summary.append("\nExtracted HTML content:")
            summary.append(result["html"])

        # Add complete geometry details if present
        if result.get("has_geometry", False) and "details" in result and "geometry_details" in result["details"]:
            summary.append("\nGeometric figure details:")
            summary.append(result["details"]["geometry_details"])

        # Add all chemical formulas
        if result.get("has_chemistry", False) and "details" in result and "chemistry_details" in result["details"]:
            summary.append("\nDetected chemical formulas (SMILES):")
            for formula in result["details"].get("chemistry_details", []):
                summary.append(f"- {formula}")

        # Include details about tables
        if result.get("has_table", False) and "details" in result and "table_details" in result["details"]:
            summary.append("\nDetailed table data:")
            # Include any additional table data that might not be in the main text
            for table in result["details"].get("table_details", []):
                if "data" in table:
                    summary.append(table["data"])

        # Include detailed math information
        if result.get("has_math", False) and "details" in result and "math_details" in result["details"]:
            summary.append("\nDetailed mathematical expressions:")
            for math_item in result["details"].get("math_details", []):
                if "value" in math_item:
                    summary.append(f"- {math_item['value']}")
                    
        # Final fallback - if we still have no content, include a message for the AI
        if not summary:
            summary.append("Image was processed but no extractable text content was found. Please analyze the visual content of the image.")
            
        # Log the final output
        formatted_output = "\n".join(summary)
        logger.debug(f"Final formatted output: {len(formatted_output)} characters")
        
        return "\n".join(summary)
    except Exception as e:
        # Catch any exceptions to make the function more robust
        logger.error(f"Error in format_mathpix_result_for_assistant: {str(e)}", exc_info=True)
        # Return a fallback message if formatting fails completely
        return "Image content was processed but could not be properly formatted. Please analyze the image visually."

def process_geometry_data(geometry_data):
    """
    Process geometric data into a readable format
    """
    if not geometry_data:
        return "No geometric figures detected."

    result_parts = ["Geometric figure detected:"]

    for figure in geometry_data:
        shape_list = figure.get("shape_list", [])
        label_list = figure.get("label_list", [])

        for shape in shape_list:
            shape_type = shape.get("type", "unknown")
            result_parts.append(f"- Type: {shape_type}")

            if shape_type == "triangle":
                vertices = shape.get("vertex_list", [])
                result_parts.append(f"- Number of vertices: {len(vertices)}")

                # Add vertex coordinates
                result_parts.append("- Vertex coordinates:")
                for i, vertex in enumerate(vertices):
                    result_parts.append(f"  * Vertex {i+1}: ({vertex.get('x')}, {vertex.get('y')})")

        # Process labels (text and values)
        if label_list:
            result_parts.append("- Detected labels:")
            for label in label_list:
                label_text = label.get("text", "")
                position = label.get("position", {})
                result_parts.append(f"  * {label_text} - Position: ({position.get('top_left_x', 'N/A')}, {position.get('top_left_y', 'N/A')})")

    return "\n".join(result_parts)