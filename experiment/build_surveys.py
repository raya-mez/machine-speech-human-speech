"""Builds a Qualtrics survey file for one generation by populating a template file with content for each chain.
The resulting file is uploaded to Qualtrics to be published. 

Usage (example for generation 1):
	python scripts/survey_versioning/build_surveys.py --gen 1
"""

import re
import copy
import json
import argparse


# --- UTILITY FUNCTIONS ---
def load_json(path):
	with open(path) as f:
		return json.load(f)


# will be used to display the target text in the survey
def make_paragraphs_html(text):
	"""Wrap paragraphs split by blank lines in <p> tags"""
	paragraphs = text.strip().split("\n\n")
	return f"   <p>{paragraphs[0]}</p>\n        " + "\n        ".join(
		f"   <p>{p.strip()}</p>" for p in paragraphs[1:] if p.strip()
	)

def get_sq_payload(survey_template, qid):
	"""Get the payload of a survey question (SQ) element by its QuestionID (qid)"""
	sq_element = next(
		e
		for e in survey_template["SurveyElements"]
		if e.get("Element") == "SQ" and e.get("Payload", {}).get("QuestionID") == qid
	)
	return sq_element["Payload"]


def iter_flow_nodes(flow_node):
	yield flow_node
	for child in flow_node.get("Flow", []):
		yield from iter_flow_nodes(child)


def next_bl_payload_key(bl_payload):
	numeric_keys = [int(k) for k in bl_payload.keys() if str(k).isdigit()]
	return str(max(numeric_keys) + 1) if numeric_keys else "0"


def max_qid_num(survey_template):
	max_id = 0
	for e in survey_template["SurveyElements"]:
		if e.get("Element") != "SQ":
			continue
		qid = e.get("Payload", {}).get("QuestionID", "")
		m = re.fullmatch(r"QID(\d+)", str(qid))
		if m:
			max_id = max(max_id, int(m.group(1)))
	return max_id


def max_flow_id_num(flow_root):
	max_id = 0
	for node in iter_flow_nodes(flow_root):
		flow_id = node.get("FlowID")
		m = re.fullmatch(r"FL_(\d+)", str(flow_id))
		if m:
			max_id = max(max_id, int(m.group(1)))
	return max_id


def assign_new_flow_ids(flow_node, next_flow_id):
	for node in iter_flow_nodes(flow_node):
		if "FlowID" in node:
			next_flow_id += 1
			node["FlowID"] = f"FL_{next_flow_id}"
	return next_flow_id


def remap_chain_export_tag(tag, chain_id, source_chain_id="0"):
	if not isinstance(tag, str):
		return tag
	pattern = rf"^(.*_c){re.escape(str(source_chain_id))}$"
	return re.sub(pattern, rf"\g<1>{chain_id}", tag)


def apply_chain_export_tags_to_block(survey_elements, block, chain_id, source_chain_id="0"):
	block_qids = {
		be.get("QuestionID")
		for be in block.get("BlockElements", [])
		if be.get("Type") == "Question"
	}

	for sq in survey_elements:
		if sq.get("Element") != "SQ":
			continue
		payload = sq.get("Payload", {})
		qid = payload.get("QuestionID")
		if qid not in block_qids:
			continue
		if isinstance(payload.get("DataExportTag"), str):
			payload["DataExportTag"] = remap_chain_export_tag(
				payload["DataExportTag"],
				chain_id,
				source_chain_id=source_chain_id,
			)


def replace_qid_references(obj, old_qid, new_qid):
	if isinstance(obj, dict):
		for key, value in obj.items():
			if isinstance(value, (dict, list)):
				replace_qid_references(value, old_qid, new_qid)
			elif isinstance(value, str):
				obj[key] = re.sub(rf"\b{re.escape(old_qid)}\b", new_qid, value)
	elif isinstance(obj, list):
		for idx, value in enumerate(obj):
			if isinstance(value, (dict, list)):
				replace_qid_references(value, old_qid, new_qid)
			elif isinstance(value, str):
				obj[idx] = re.sub(rf"\b{re.escape(old_qid)}\b", new_qid, value)


def add_main_task_blocks_and_branches(survey_template, chain_ids):
	if not chain_ids:
		raise RuntimeError("No chain IDs found in chain_data.")

	# the template contains one canonical main-task block and branch for c0
	# clone and retarget that structure for every other chain
	bl_element = next(e for e in survey_template["SurveyElements"] if e.get("Element") == "BL")
	bl_payload = bl_element["Payload"]
	fl_element = next(e for e in survey_template["SurveyElements"] if e.get("Element") == "FL")
	flow_root = fl_element["Payload"]
	survey_elements = survey_template["SurveyElements"]

	# find block and branch corresponding to c0 
	source_block_key = next(
		k for k, b in bl_payload.items() if b.get("Description") == "Main task c0"
	)
	source_block = bl_payload[source_block_key] # block to be cloned for each chain
	source_block_id = source_block["ID"] # id of the block

	# find the survey questions (SQ) that belong to the source block => to clone them for each chain
	source_question_ids = [
		be["QuestionID"]
		for be in source_block.get("BlockElements", [])
		if be.get("Type") == "Question"
	]
	# mapping QuestionID to corresponding SQ element for the c0 block
	source_sq_by_qid = {
		sq["Payload"]["QuestionID"]: sq
		for sq in survey_elements
		if sq.get("Element") == "SQ" and sq.get("Payload", {}).get("QuestionID") in source_question_ids
	}

	# find the branch in the flow that points to the source block => to clone its logic for each chain
	source_branch_idx = None
	source_branch = None
	flow_items = flow_root.get("Flow", [])
	for idx, item in enumerate(flow_items):
		if item.get("Type") != "Branch":
			continue
		branch_expr = item.get("BranchLogic", {}).get("0", {}).get("0", {}) # the branch expression that checks the chain id
		branch_flow = item.get("Flow", []) # the flow items under this branch
		if (
			branch_expr.get("LogicType") == "EmbeddedField"
			and branch_expr.get("LeftOperand") == "c"
			and str(branch_expr.get("RightOperand")) == "0"
			and any(f.get("ID") == source_block_id for f in branch_flow if f.get("Type") == "Block")
		):
			source_branch_idx = idx
			source_branch = item
			break

	# if source_branch is None:
	# 	raise RuntimeError("Could not find source branch for Main task c0.")

	# reuse the c0 branch as the first real chain, then clone it for the rest
	first_chain = str(chain_ids[0])
	# update the source block and branch to point to the first chain instead of c0
	source_block["Description"] = f"Main task c{first_chain}"
	source_block["ID"] = f"BL_MAINTASK_C{first_chain}"
	# update the DataExportTag of each SQ in the source block to point to the first chain instead of c0
	apply_chain_export_tags_to_block(
		survey_elements,
		source_block,
		first_chain,
		source_chain_id="0",
	)
	# update the branch logic to point to the first chain instead of c0
	source_branch["BranchLogic"]["0"]["0"]["RightOperand"] = first_chain
	for f_item in source_branch.get("Flow", []):
		if f_item.get("Type") == "Block":
			f_item["ID"] = source_block["ID"]

	# clone the source block and branch for each remaining chain
	qid_counter = max_qid_num(survey_template)
	next_flow_id = max_flow_id_num(flow_root)
	new_branches = []

	for c in [str(cid) for cid in chain_ids[1:]]:
		block_clone = copy.deepcopy(source_block)
		# update description & ID of new block to match new chain
		block_clone["Description"] = f"Main task c{c}"
		block_clone["ID"] = f"BL_MAINTASK_C{c}"

		# clone the SQs in the source block and give them new QIDs
		qid_map = {}
		for be in block_clone.get("BlockElements", []):
			if be.get("Type") != "Question":
				continue
			old_qid = be["QuestionID"]
			if old_qid not in qid_map:
				qid_counter += 1
				qid_map[old_qid] = f"QID{qid_counter}"
			be["QuestionID"] = qid_map[old_qid]

		for old_qid, new_qid in qid_map.items():
			sq_clone = copy.deepcopy(source_sq_by_qid[old_qid])
			sq_clone["PrimaryAttribute"] = new_qid
			payload = sq_clone["Payload"]
			payload["QuestionID"] = new_qid
			payload["DataExportTag"] = remap_chain_export_tag(
				payload.get("DataExportTag"),
				c,
				source_chain_id=first_chain,
			)
			replace_qid_references(sq_clone, old_qid, new_qid)
			survey_elements.append(sq_clone)

		new_key = next_bl_payload_key(bl_payload)
		bl_payload[new_key] = block_clone

		# clone the source branch and update its logic to point to the new chain
		branch_clone = copy.deepcopy(source_branch)
		next_flow_id = assign_new_flow_ids(branch_clone, next_flow_id)
		branch_clone["BranchLogic"]["0"]["0"]["RightOperand"] = c
		for f_item in branch_clone.get("Flow", []):
			if f_item.get("Type") == "Block":
				f_item["ID"] = block_clone["ID"]
		new_branches.append(branch_clone)

	# insert the all new branches into the flow after the source (c0) branch
	insert_at = source_branch_idx + 1
	for i, branch in enumerate(new_branches):
		flow_items.insert(insert_at + i, branch)


def collect_qids_by_chain(survey_template, chain_ids):
	"""Collects the QIDs of the three main task questions for each chain in the survey template"""
	bl_element = next(e for e in survey_template["SurveyElements"] if e.get("Element") == "BL")
	bl_payload = bl_element["Payload"]
	qids_by_chain = {}

	for c in [str(cid) for cid in chain_ids]:
		# find the block that belongs to each chain => to update its texts
		for block in bl_payload.values():
			if block.get("Description") == f"Main task c{c}":
				qids = [
					be["QuestionID"]
					for be in block.get("BlockElements", [])
					if be.get("Type") == "Question"
				]
				qids_by_chain[c] = qids
				break
		# else:
		# 	raise RuntimeError(f"Could not find Main task block for chain {c}.")

	return qids_by_chain


def apply_chain_placeholders(text, chain_entry, chain_data):
	"""Replace placeholders in the template text with chain-specific content from chain_entry and chain_data"""
    
	out = text
	# replace placeholders related to the example texts
	for n in range(1, 3):
		# get chain id for current example
		example_chain = str(chain_entry["example_chain_ids"][n - 1])
		out = out.replace(f"__EXAMPLE_{n}_TITLE__", chain_data[example_chain]["target_title"])
		out = out.replace(
			f"__EXAMPLE_{n}_PARAGRAPHS_HTML__",
			make_paragraphs_html(chain_data[example_chain]["target_text"]),
		)

	# replace placeholders related to the target text
	out = out.replace("__TARGET_TITLE__", chain_entry["target_title"])
	out = out.replace("__TARGET_PARAGRAPHS_HTML__", make_paragraphs_html(chain_entry["target_text"]))
	out = out.replace("__SENTENCE_LIST__", json.dumps(chain_entry["target_sentence_list"]))
	return out


def inject_chain_content_from_embedded_template(survey_template, chain_data, chain_ids):
	"""Inject chain-specific content (HTML or JS string) into the survey template for each chain."""
	# collect the QIDs of the main task questions for each chain that need to be updated with chain-specific content
	qids_by_chain = collect_qids_by_chain(survey_template, chain_ids)

	for c in [str(cid) for cid in chain_ids]:
		# get the chain-specific content for this chain
		chain_entry = chain_data[c]
		for qid in qids_by_chain[c]:
			payload = get_sq_payload(survey_template, qid)
			# update the relevant fields in the payload with chain-specific content
			for field in ["QuestionText", "QuestionText_Unsafe", "QuestionJS"]: 
				if field in payload and isinstance(payload[field], str):
					payload[field] = apply_chain_placeholders(payload[field], chain_entry, chain_data)


def parse_args():
	parser = argparse.ArgumentParser(description="Build populated survey JSON/QSF for a generation.")
	parser.add_argument("--gen")
	parser.add_argument("--survey-template", default="surveys/template_chain0.json")
	parser.add_argument("--survey-name", default=None)
	parser.add_argument("--survey_input_data", default=None)
	parser.add_argument("--output-json", default=None)
	parser.add_argument("--output-qsf", default=None)
	return parser.parse_args()


def main():
	args = parse_args()

	# default inputs and outputs based on generation number
	survey_input_data_file = args.survey_input_data or f"data/survey_input_data/gen{args.gen}_survey_input_data.json"
	output_survey_json = args.output_json or f"survey_files/survey_gen{args.gen}.json"
	output_survey_qsf = args.output_qsf or f"survey_files/survey_gen{args.gen}.qsf"

	survey_template = load_json(args.survey_template)
	survey_input_data = load_json(survey_input_data_file)
	chain_ids = [str(cid) for cid in survey_input_data.keys()]
	print(f"Building survey for gen {args.gen} with chains: {', '.join(chain_ids)}")

	# add blocks and branches for each chain by cloning c0
	add_main_task_blocks_and_branches(survey_template, chain_ids)
	# fill them in with chain-specific content
	inject_chain_content_from_embedded_template(survey_template, survey_input_data, chain_ids)

	if args.survey_name:
		survey_template.setdefault("SurveyEntry", {})["SurveyName"] = args.survey_name
	else:
		survey_template.setdefault("SurveyEntry", {})["SurveyName"] = (
			f"Machine speech, human speech - G{args.gen}"
		)

	with open(output_survey_json, "w") as f:
		json.dump(survey_template, f, indent=4)

	with open(output_survey_qsf, "w") as f:
		json.dump(survey_template, f, indent=4)

	print(f"Built survey for gen {args.gen}: {output_survey_json} and {output_survey_qsf}")


if __name__ == "__main__":
	main()