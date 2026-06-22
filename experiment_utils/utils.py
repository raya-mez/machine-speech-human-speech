import base64
import json
import urllib.parse

def decode_qualtrics_data(encoded_str, skip_missing=False):
    """Decode stringified JSON data, encoded with base64 and URI encoding in Quatrics JavaScript snippets"""
    # handle missing data (e.g., from incomplete survey responses)
    if skip_missing and not isinstance(encoded_str, str):
        print(f"Warning: Expected a string to decode but got {type(encoded_str)}. Skipping entry: {encoded_str}")
        return encoded_str
    # decode base64
    decoded_bytes = base64.b64decode(encoded_str)
    # decode URI components (reverses the encodeURIComponent/unescape)
    decoded_str = urllib.parse.unquote(decoded_bytes.decode('utf-8'))
    # parse JSON
    return json.loads(decoded_str)

def map_edit_to_explanation(edits_json, explanation_json):
    """Map each sentence editing pair (original and edited sentence) to its explanation by sentence index.

    Args:
        edits (list[dict]): list of dictionaries with ``orig`` and ``edited`` keys.
        explanations (list[dict]): list of explanation dictionaries with ``index`` and ``explanation`` keys.

    Returns:
        dict[int, dict]: dictionary keyed by edit index. 
            Each value contains the original text, edited text, and the matched explanation. 
            If no explanation exists for a given edit index, NA is used.
    """
    explanation_map = {explanation_json[i]['index']: explanation_json[i]['explanation'] for i in range(len(explanation_json))}
    
    edits_dict = {}
    for i, sentence in enumerate(edits_json):
        # use the explanation if it exists for this index, else use placeholder
        explanation = explanation_map.get(i, "NA")
        edits_dict[i] = {
            'orig': sentence['orig'], 
            'edited': sentence['edited'], 
            'explanation': explanation
        }
    return edits_dict

