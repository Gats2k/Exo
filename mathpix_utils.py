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

        # Configuration simplifiée mais efficace pour la détection mathématique
        payload = {
            "src": f"data:image/jpeg;base64,{image_data}",
            "formats": ["text", "data", "html"],
            "data_options": {
                "include_asciimath": True,
                "include_latex": True
            },
            "include_geometry_data": True
        }

        # Send request to Mathpix
        url = "https://api.mathpix.com/v3/text"
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()

        result = response.json()

        # Structure the response
        structured_result = {
            "text": result.get("text", ""),
            "has_math": False,
            "has_table": False,
            "has_chemistry": False,
            "has_geometry": False,
            "details": {}
        }

        # Process mathematical data
        if "data" in result:
            for data_item in result["data"]:
                if data_item.get("type") in ["latex", "asciimath", "mathml"]:
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

        # Check for chemical formulas (SMILES)
        if "text" in result:
            smiles_pattern = r'<smiles.*?>(.*?)</smiles>'
            smiles_matches = re.findall(smiles_pattern, result["text"])

            if smiles_matches:
                structured_result["has_chemistry"] = True
                structured_result["details"]["chemistry_details"] = smiles_matches

        # Format summary for assistant (now also sets the formatted_summary and formatted_full_data fields)
        format_mathpix_result_for_assistant(structured_result)
        
        return structured_result

    except Exception as e:
        logger.error(f"Error processing image with Mathpix: {str(e)}")
        return {"error": f"Error processing image: {str(e)}"}

def format_mathpix_result_for_assistant(result):
    """
    Format Mathpix results into a well-structured text summary for the assistant
    """
    summary = []
    full_data = []

    # Add header based on content
    content_types = []
    if result["has_math"]: content_types.append("mathematical formulas")
    if result["has_table"]: content_types.append("tables")
    if result["has_chemistry"]: content_types.append("chemical formulas")
    if result["has_geometry"]: content_types.append("geometric figures")

    if content_types:
        summary.append(f"Image contains {', '.join(content_types)}.")
        full_data.append(f"Image contains {', '.join(content_types)}.")

    # Add main text
    if result.get("text"):
        summary.append("\nExtracted content:")
        summary.append(result["text"])
        
        full_data.append("\nExtracted content:")
        full_data.append(result["text"])

    # Add math details
    if result["has_math"] and "math_details" in result["details"]:
        full_data.append("\nMathematical formulas details:")
        for math_item in result["details"]["math_details"]:
            math_type = math_item.get("type", "unknown")
            math_value = math_item.get("value", "")
            if math_value:
                full_data.append(f"- {math_type}: {math_value}")

    # Add all table details
    if result["has_table"] and "table_details" in result["details"]:
        full_data.append("\nTable details:")
        for table_item in result["details"]["table_details"]:
            table_type = table_item.get("type", "unknown")
            table_value = table_item.get("value", "")
            if table_value:
                full_data.append(f"- {table_type}:")
                full_data.append(table_value)

    # Add geometry details if present
    if result["has_geometry"] and "geometry_details" in result["details"]:
        summary.append("\nGeometric figure details:")
        summary.append(result["details"]["geometry_details"])
        
        full_data.append("\nGeometric figure details:")
        full_data.append(result["details"]["geometry_details"])

    # Add chemical formulas
    if result["has_chemistry"] and "chemistry_details" in result["details"]:
        summary.append("\nDetected chemical formulas (SMILES):")
        full_data.append("\nDetected chemical formulas (SMILES):")
        
        for formula in result["details"]["chemistry_details"]:
            summary.append(f"- {formula}")
            full_data.append(f"- {formula}")

    # Mention tables specifically in the summary
    if result["has_table"]:
        summary.append("\nA table was detected in the image. The data is included in the text above.")
    
    # Store both versions
    result["formatted_summary"] = "\n".join(summary)  # For UI display
    result["formatted_full_data"] = "\n".join(full_data)  # Complete data for AI
    
    return result["formatted_summary"]

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