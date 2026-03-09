with open(r"c:\Users\IbrahimBashar\Downloads\iterative_quality_assurance_pipeline_with_test_fix_loops_v1_crewai-project\src\iterative_quality_assurance_pipeline_with_test_fix_loops\crew.py", "r") as f:
    text = f.read()

text = text.replace("gemini_llm", "local_llm")
text = text.replace(
    'model="gemini/gemini-2.5-pro",\n    api_key="AIzaSyDz2dvL_k1GKrCqZkorsnZ7oGl79Dktnis"',
    'model="ollama/llama3",\n    base_url="http://localhost:11434"'
)
text = text.replace('Gemini LLM', 'Ollama LLM')

with open(r"c:\Users\IbrahimBashar\Downloads\iterative_quality_assurance_pipeline_with_test_fix_loops_v1_crewai-project\src\iterative_quality_assurance_pipeline_with_test_fix_loops\crew.py", "w") as f:
    f.write(text)

print("success")
