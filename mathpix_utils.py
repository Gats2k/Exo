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

    logger.info(f"Mathpix credentials check: APP_ID={'set' if MATHPIX_APP_ID else 'missing'}, APP_KEY={'set' if MATHPIX_APP_KEY else 'missing'}")

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

        # Configuration avancée pour détecter math, chimie, géométrie ET schémas biologiques
        payload = {
            "src": f"data:image/jpeg;base64,{image_data}",
            "formats": ["text", "data", "html"],
            "data_options": {
                "include_asciimath": True,
                "include_latex": True
            },
            "include_geometry_data": True,
            "include_diagram_data": True,  # Détection de diagrammes (schémas SVT)
            "include_line_data": True,      # Détection de lignes/flèches (connexions anatomiques)
            "alphabets": {
                "allow_all": True  # Permet la détection de tous les alphabets (labels en français)
            }
        }

        # Send request to Mathpix
        url = "https://api.mathpix.com/v3/text"
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()

        result = response.json()
        logger.info(f"Mathpix response status: {response.status_code}")
        logger.debug(f"Mathpix raw result: {result}")
        logger.info(f"Mathpix extracted text length: {len(result.get('text', ''))}")

        # Structure the response
        structured_result = {
            "text": result.get("text", ""),
            "has_math": False,
            "has_table": False,
            "has_chemistry": False,
            "has_geometry": False,
            "has_diagram": False,  # Schémas biologiques/anatomiques
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

        # Process diagram data (schémas biologiques/anatomiques)
        if "diagram_data" in result and result["diagram_data"]:
            structured_result["has_diagram"] = True
            structured_result["details"]["diagram_details"] = process_diagram_data(result["diagram_data"])

        # Check for chemical formulas (SMILES)
        if "text" in result:
            smiles_pattern = r'<smiles.*?>(.*?)</smiles>'
            smiles_matches = re.findall(smiles_pattern, result["text"])

            if smiles_matches:
                structured_result["has_chemistry"] = True
                structured_result["details"]["chemistry_details"] = smiles_matches

        # Format summary for assistant
        formatted_summary = format_mathpix_result_for_assistant(structured_result)
        structured_result["formatted_summary"] = formatted_summary

        return structured_result

    except Exception as e:
        logger.error(f"Error processing image with Mathpix: {str(e)}")
        return {"error": f"Error processing image: {str(e)}"}

def format_mathpix_result_for_assistant(result):
    """
    Format Mathpix results into a well-structured text summary for the assistant
    """
    summary = []

    # Add header based on content
    content_types = []
    if result["has_math"]: content_types.append("mathematical formulas")
    if result["has_table"]: content_types.append("tables")
    if result["has_chemistry"]: content_types.append("chemical formulas")
    if result["has_geometry"]: content_types.append("geometric figures")
    if result["has_diagram"]: content_types.append("biological/anatomical diagrams")

    if content_types:
        summary.append(f"Image contains {', '.join(content_types)}.")

    # Add main text
    if result.get("text"):
        summary.append("\nExtracted content:")
        summary.append(result["text"])

    # Add geometry details if present
    if result["has_geometry"] and "geometry_details" in result["details"]:
        summary.append("\nGeometric figure details:")
        summary.append(result["details"]["geometry_details"])

    # Add diagram details (schémas SVT/anatomiques)
    if result["has_diagram"] and "diagram_details" in result["details"]:
        summary.append("\nBiological/Anatomical diagram detected:")
        summary.append(result["details"]["diagram_details"])

    # Add chemical formulas
    if result["has_chemistry"] and "chemistry_details" in result["details"]:
        summary.append("\nDetected chemical formulas (SMILES):")
        for formula in result["details"]["chemistry_details"]:
            summary.append(f"- {formula}")

    # Mention tables specifically
    if result["has_table"]:
        summary.append("\nA table was detected in the image. The data is included in the text above.")

    return "\n".join(summary)

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

def process_diagram_data(diagram_data):
    """
    Process diagram data (biological/anatomical schemas) into a readable format
    Détecte et analyse les schémas SVT (appareil digestif, cœur, systèmes anatomiques, etc.)
    """
    if not diagram_data:
        return "No biological/anatomical diagram detected."

    result_parts = ["Biological/Anatomical diagram detected:"]

    # Mathpix peut retourner différents types de données pour les diagrammes
    if isinstance(diagram_data, list):
        for idx, diagram in enumerate(diagram_data):
            result_parts.append(f"\n--- Diagram {idx + 1} ---")
            
            # Extraire les composants du diagramme
            if isinstance(diagram, dict):
                # Labels/annotations (noms des organes, parties anatomiques)
                if "labels" in diagram or "text_regions" in diagram:
                    labels = diagram.get("labels", diagram.get("text_regions", []))
                    if labels:
                        result_parts.append("Detected labels/annotations:")
                        for label in labels:
                            if isinstance(label, dict):
                                text = label.get("text", label.get("content", ""))
                                if text:
                                    result_parts.append(f"  • {text}")
                            elif isinstance(label, str):
                                result_parts.append(f"  • {label}")
                
                # Connexions/flèches (relations entre organes)
                if "connections" in diagram or "arrows" in diagram or "lines" in diagram:
                    connections = diagram.get("connections", diagram.get("arrows", diagram.get("lines", [])))
                    if connections:
                        result_parts.append("Detected connections/arrows:")
                        result_parts.append(f"  • Number of connections: {len(connections)}")
                
                # Régions/zones (organes, parties du corps)
                if "regions" in diagram or "shapes" in diagram:
                    regions = diagram.get("regions", diagram.get("shapes", []))
                    if regions:
                        result_parts.append("Detected regions/shapes:")
                        result_parts.append(f"  • Number of regions: {len(regions)}")
    
    elif isinstance(diagram_data, dict):
        # Traiter un seul diagramme
        if "labels" in diagram_data or "text_regions" in diagram_data:
            labels = diagram_data.get("labels", diagram_data.get("text_regions", []))
            if labels:
                result_parts.append("Detected labels/annotations:")
                for label in labels:
                    if isinstance(label, dict):
                        text = label.get("text", label.get("content", ""))
                        if text:
                            result_parts.append(f"  • {text}")
                    elif isinstance(label, str):
                        result_parts.append(f"  • {label}")
        
        if "connections" in diagram_data:
            result_parts.append(f"Detected connections: {len(diagram_data['connections'])}")
    
    # Si aucune donnée structurée n'est disponible, indiquer qu'un diagramme a été détecté
    if len(result_parts) == 1:
        result_parts.append("A complex diagram was detected. The text content has been extracted above.")
        result_parts.append("This may include: anatomical structures, biological systems, or scientific illustrations.")
    
    return "\n".join(result_parts)

