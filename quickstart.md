# Quickstart

## Download the final zip
If you want to use the final dataset with all .txt files, download it from: TODO

## Repo Layout
`data_clean` contains the generated simulated company data.
`data_noisy` contains the company data after adding noise (scrambling, adding contractions, etc.).
`code` contains utilities for generating and manipulating the data.

To create your own dataset, erase `data_clean` and `data_noisy` then run the scripts in `code/data_scripts` in order.
> Note: You'll need to run `export OPENAI_API_KEY=<your-key>` and `export LLM_MODEL=gpt-4o-mini`

If you wish to use other models, there is an LLM interface which you can implement at `code/llm/interface.py`.
