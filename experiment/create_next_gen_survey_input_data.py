"""Creates input data for the next survey generation based on the previous generation's responses.

Usage:
    python scripts/survey_versioning/create_next_gen_survey_input_data.py --new_gen 2
"""

import os
import sys
import json
import nltk
import argparse
import pandas as pd
from openai import OpenAI
from dotenv import load_dotenv

# change working directory to root of repository 
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from experiment_utils.utils import *


def generate_examples(client, example_edits, title, input_text):
    model = "gpt-5.2-chat-latest"
    prompt = f"""You are an advanced language model. Humans have edited your output to make it appear more convincingly human-written and provided explanations for the edits. You have learned from this editing. Now, you will be given a new text to edit in the same way. 

# OBSERVED EDITS AND EXPLANATIONS
{example_edits}

# INSTRUCTIONS
- Infer the strategies humans used in the edits above and apply analogous strategies to the new text below.
- You may rephrase, add, or remove content, merge or split sentences.

# NEW TEXT
Title: {title}
{input_text}

# OUTPUT
Return ONLY the fully edited text (without the title). No explanations or annotations."""

    response = client.responses.create(model=model, input=prompt)
    return response.output_text.strip()


tokenizer = nltk.data.load('tokenizers/punkt/english.pickle')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--new_gen")
    args = parser.parse_args()

    new_gen = int(args.new_gen)
    processed_resp_data_path = f"data/processed/responses_gen{new_gen - 1}_processed.csv"
    prev_survey_data_path = f"data/survey_input_data/gen{new_gen - 1}_survey_input_data.json"
    new_survey_data_path = f"data/survey_input_data/gen{new_gen}_survey_input_data.json"
    stopping_chains_data_path = "data/dynamic/stopping_chains.json"

    with open(processed_resp_data_path, 'r') as f:
        prev_gen_resp_data = pd.read_csv(f)

    with open(prev_survey_data_path, 'r') as f:
        prev_gen_survey_data = json.load(f)

    with open(stopping_chains_data_path, 'r') as f:
        stopping_chains_data = json.load(f)


    # --- CHAIN CONTINUATION AND STOPPING ---
    print("--- CHAIN DATA CHECKS ---")
    # check that there is exactly one response for each initialized chain
    initialized_chains_prev_gen = [int(c) for c in prev_gen_survey_data.keys()]
    missing_chains = set(initialized_chains_prev_gen) - set(prev_gen_resp_data['c'].unique())
    duplicate_chains = len(prev_gen_resp_data['c'].unique()) > len(initialized_chains_prev_gen)
    if missing_chains:
        print(f"{len(missing_chains)} initialized chain(s) are missing responses: {sorted(missing_chains)}")
    elif duplicate_chains:
        print(f"There are {len(duplicate_chains)} duplicate chains in the responses: {sorted(duplicate_chains)}")
    else:
        print("All initialized chains from the previous generation have unique responses.")

    # chains with stopping criterion flagged
    chains_stop_crit = prev_gen_resp_data[prev_gen_resp_data['stop_crit'] == 'No']['c'].tolist()
    print(f"Chains with stopping criterion flagged (stop_crit == 'No'): {chains_stop_crit}")

    if new_gen == 2:
        chains_to_stop = [] 
    else:
        prev_gen_flagged_chains = stopping_chains_data[f"gen{new_gen - 2}"]
        chains_to_stop = sorted(set(chains_stop_crit).intersection(set(prev_gen_flagged_chains)))

    # save updated stopping chains data to json file
    stopping_chains_data[f"gen{new_gen - 1}"] = {
        "flagged": chains_stop_crit,
        "stopped": chains_to_stop
    }
    with open(stopping_chains_data_path, 'w') as f:
        json.dump(stopping_chains_data, f, indent=4)    
    print(f"Updated stopping chains data with gen{new_gen - 1}: {stopping_chains_data[f'gen{new_gen - 1}']}. Saved to {stopping_chains_data_path}")

    # sort data by chain id and remove stopping chains
    continuing_chains = prev_gen_resp_data.sort_values(by='c')
    continuing_chains = continuing_chains[~continuing_chains['c'].isin(chains_to_stop)]
    print(f"Continuing chains: {list(continuing_chains['c'].unique())}\n")


    # --- TEXT GENERATION ---
    # function to generate examples based on edits in current chain and texts in example chains
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    client = OpenAI(api_key=api_key)


    # --- CREATE NEW SURVEY INPUT DATA ---
    new_survey_data = {}
    print("--- GENERATING EXAMPLE TEXTS ---")

    # iterate through each chain entry in the previous generation data
    # and use the relevant info to create survey data for the next generation
    for idx, row in continuing_chains.iterrows():
        chain = str(row['c'])
        print(f"Processing chain {chain} (row {idx})...")
		
        # find the corresponding survey input entry in prev_gen_survey_data
        chain_data_entry = prev_gen_survey_data.get(chain)
		
        # TEXT STIMULUS
        # >> recreate stimulus text by concatenating edited sentences in edit_pairs and reconstructing paragraph breaks based on end_of_paragraph_sentences_indices
		
        # get edit pairs for current chain and decode them
        edit_pairs = decode_qualtrics_data(row['EditPairsJSON'])
		
        # concatenate edited sentences in edit_pairs into a single string
        # append \n\n after sentences at indices specified in chain_data_entry['end_of_paragraph_sentences_indices'] to reconstruct paragraph breaks
        edited_text = ""
        for i, pair in enumerate(edit_pairs):
            edited_text += pair['edited'].strip()
            if i in chain_data_entry['end_of_paragraph_sentences_indices']:
                edited_text += "\n\n"
            else:
                edited_text += " "
		
        # STIMULUS SENTENCES
        # redefine the list of sentences as some may have been split, merged, or deleted
        sentences = []
        paragraphs = [p.strip() for p in edited_text.split("\n\n") if p.strip()]
        end_of_paragraph_indices = []
        for p in paragraphs:
            sentences.extend([s.strip() for s in tokenizer.tokenize(p)])
            end_of_paragraph_indices.append(len(sentences) - 1)

        # generate new example texts by imitating edit data from previous generation on texts from example chains
        explanations = decode_qualtrics_data(row['EditExplanationsJSON'])
        example_edits = map_edit_to_explanation(edit_pairs, explanations)

        # find example titles and texts
        print(f"Generating example texts...")
        example1_text = generate_examples(client, example_edits, chain_data_entry['example1_title'], chain_data_entry['example1_text'])
        example2_text = generate_examples(client, example_edits, chain_data_entry['example2_title'], chain_data_entry['example2_text'])

        new_survey_data[chain] = {
            "stimulus_title": chain_data_entry['stimulus_title'],
            "stimulus_text": edited_text.strip(),
            "stimulus_sentence_list": sentences,
            "end_of_paragraph_sentences_indices": end_of_paragraph_indices, # NOTE: 0-indexed
            "example_chain_ids": chain_data_entry['example_chain_ids'],  # keep example chain ids the same as before 
            "example1_title": chain_data_entry['example1_title'], # example titles also stay the same
            "example1_text": example1_text,
            "example2_title": chain_data_entry['example2_title'],
            "example2_text": example2_text,
        }
		
    with open(new_survey_data_path, "w") as f:
        json.dump(new_survey_data, f, ensure_ascii=False)
    print(f"Created new survey input data for generation {new_gen} with {len(new_survey_data)} chains (after removing stopped chains).\nSaved to {new_survey_data_path}.")


if __name__ == "__main__":
    main()