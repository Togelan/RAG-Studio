---
name: langsmith-eval
description: LangSmith evaluation workflows — creating datasets with synthetic questions, running RAGAS metrics (faithfulness, context_recall, answer_relevancy), and parsing experiment results. Use when running QA evaluations against RAG-Studio.
---

# LangSmith Evaluation Skill

## When to Use

Invoke this skill when:
- Running RAGAS evaluation on RAG-Studio
- Creating synthetic test datasets in LangSmith
- Verifying RAGAS thresholds (faithfulness > 0.7, context_recall > 0.8)
- Generating experiment reports for @architect

---

## 1. Setting Up LangSmith

```python
import os
from langsmith import Client

# Environment variables (set before running)
# LANGCHAIN_API_KEY=lsv2_...
# LANGCHAIN_PROJECT=rag-studio-eval
# LANGCHAIN_ENDPOINT=https://api.smith.langchain.com

client = Client()

# Verify connection
print(f"LangSmith project: {os.getenv('LANGCHAIN_PROJECT')}")
print(f"Datasets available: {client.list_datasets()}")
```

---

## 2. Creating a LangSmith Dataset with Synthetic Questions

```python
from langsmith import Client
from langsmith.schemas import DataType, Example

client = Client()

# Define 40 synthetic question-answer pairs
# Grouped by category for coverage
SYNTHETIC_QUESTIONS = [
    # Factual lookup (10)
    {"question": "What is the capital of France?", "reference": "Paris is the capital of France."},
    {"question": "Who wrote 'Pride and Prejudice'?", "reference": "Jane Austen wrote 'Pride and Prejudice'."},
    {"question": "What year did World War II end?", "reference": "World War II ended in 1945."},
    {"question": "What is the chemical symbol for gold?", "reference": "The chemical symbol for gold is Au."},
    {"question": "How many continents are there on Earth?", "reference": "There are seven continents on Earth."},
    {"question": "What is the speed of light in vacuum?", "reference": "The speed of light in vacuum is approximately 299,792,458 meters per second."},
    {"question": "Who painted the Mona Lisa?", "reference": "Leonardo da Vinci painted the Mona Lisa."},
    {"question": "What is the largest planet in our solar system?", "reference": "Jupiter is the largest planet in our solar system."},
    {"question": "What does DNA stand for?", "reference": "DNA stands for deoxyribonucleic acid."},
    {"question": "In what year did the Titanic sink?", "reference": "The Titanic sank in 1912."},

    # Multi-hop reasoning (10)
    {"question": "Which country has a larger population: India or China?", "reference": "As of recent data, India has surpassed China to become the world's most populous country."},
    {"question": "If water freezes at 0°C and boils at 100°C, what is the midpoint in Celsius?", "reference": "The midpoint between freezing and boiling is 50°C."},
    {"question": "Which is farther from the Sun: Mars or Jupiter?", "reference": "Jupiter is farther from the Sun than Mars."},
    {"question": "Who became US president after Abraham Lincoln was assassinated?", "reference": "Andrew Johnson became president after Lincoln's assassination."},
    {"question": "Is a tomato a fruit or vegetable based on scientific classification?", "reference": "Botanically, a tomato is a fruit because it develops from the ovary of a flower and contains seeds."},
    {"question": "Which element has more protons: carbon or oxygen?", "reference": "Oxygen has 8 protons, while carbon has 6, so oxygen has more."},
    {"question": "What is the square root of 144?", "reference": "The square root of 144 is 12."},
    {"question": "How many hours are in a week?", "reference": "There are 168 hours in a week (24 × 7)."},
    {"question": "If a train travels at 60 mph for 2.5 hours, how far does it go?", "reference": "The train travels 150 miles."},
    {"question": "Which ocean is larger: the Atlantic or the Pacific?", "reference": "The Pacific Ocean is the largest ocean on Earth."},

    # Summary/abstractive (10)
    {"question": "Summarize the key principles of democracy.", "reference": "Key principles of democracy include popular sovereignty, political equality, majority rule with minority rights, free and fair elections, rule of law, and protection of fundamental rights and freedoms."},
    {"question": "What is the main idea of evolution by natural selection?", "reference": "Evolution by natural selection is the process where organisms better adapted to their environment tend to survive and produce more offspring, passing advantageous traits to future generations."},
    {"question": "Explain the water cycle briefly.", "reference": "The water cycle involves evaporation of water from surfaces, condensation into clouds, precipitation as rain or snow, and collection in bodies of water, repeating continuously."},
    {"question": "What are the main causes of climate change?", "reference": "Main causes include greenhouse gas emissions from burning fossil fuels, deforestation, industrial processes, and agricultural practices that release methane and CO2."},
    {"question": "Describe the structure of the United Nations.", "reference": "The UN has six main organs: General Assembly, Security Council, Economic and Social Council, Trusteeship Council, International Court of Justice, and Secretariat."},
    {"question": "What is machine learning in simple terms?", "reference": "Machine learning is a subset of AI where computers learn patterns from data to make predictions or decisions without being explicitly programmed for each task."},
    {"question": "Summarize the plot of Romeo and Juliet.", "reference": "Romeo and Juliet is a tragedy about two young star-crossed lovers from feuding families in Verona whose deaths ultimately reconcile their families."},
    {"question": "Explain how photosynthesis works.", "reference": "Photosynthesis is the process where plants use sunlight, water, and carbon dioxide to produce glucose and oxygen, occurring in chloroplasts using chlorophyll."},
    {"question": "What are the three branches of the US government?", "reference": "The three branches are Executive (President), Legislative (Congress), and Judicial (Supreme Court), providing checks and balances."},
    {"question": "Describe the theory of relativity briefly.", "reference": "Einstein's theory of relativity includes special relativity (laws of physics same in all inertial frames, E=mc²) and general relativity (gravity as curvature of spacetime by mass)."},

    # Edge cases / tricky (10)
    {"question": "What is the meaning of life?", "reference": "The meaning of life is a philosophical question with no single answer; different traditions offer different perspectives including happiness, purpose, service, or self-actualization."},
    {"question": "Is there life on Mars?", "reference": "There is currently no confirmed evidence of life on Mars, though scientists continue to search for signs of past or present microbial life."},
    {"question": "What happened to the dinosaurs?", "reference": "Dinosaurs went extinct approximately 66 million years ago, likely due to a massive asteroid impact combined with volcanic activity causing catastrophic climate change."},
    {"question": "Can you explain quantum computing simply?", "reference": "Quantum computing uses quantum bits (qubits) that can exist in multiple states simultaneously, enabling certain calculations to be performed much faster than with classical computers."},
    {"question": "What is dark matter?", "reference": "Dark matter is a hypothetical form of matter that does not emit or interact with electromagnetic radiation but is inferred from its gravitational effects on visible matter."},
    {"question": "How do vaccines work?", "reference": "Vaccines work by introducing a harmless form of a pathogen to train the immune system to recognize and fight the real pathogen if encountered later."},
    {"question": "What causes the seasons?", "reference": "Seasons are caused by Earth's axial tilt of approximately 23.5 degrees as it orbits the Sun, changing the angle and duration of sunlight received at different latitudes."},
    {"question": "What is blockchain technology?", "reference": "Blockchain is a decentralized, distributed digital ledger that records transactions across many computers in a way that makes them immutable and transparent."},
    {"question": "How does the internet work?", "reference": "The internet is a global network of computers communicating via standardized protocols (TCP/IP), routing data packets through interconnected networks using servers, routers, and cables."},
    {"question": "What is artificial general intelligence?", "reference": "Artificial General Intelligence (AGI) is a hypothetical AI that can understand, learn, and apply intelligence to solve any problem at least as well as humans across all domains."},
]


def create_eval_dataset(
    dataset_name: str = "rag-studio-qa-40",
    description: str = "40 synthetic QA pairs for RAG-Studio evaluation (RAGAS metrics)",
) -> str:
    """Create a LangSmith dataset with synthetic QA pairs.

    Returns:
        The dataset ID string.
    """
    # Check if dataset already exists
    existing = list(client.list_datasets(dataset_name=dataset_name))
    if existing:
        print(f"Dataset '{dataset_name}' already exists: {existing[0].id}")
        return str(existing[0].id)

    dataset = client.create_dataset(
        dataset_name=dataset_name,
        description=description,
        data_type=DataType.qa,  # question-answer pairs
    )

    # Create examples
    examples = [
        Example(
            inputs={"question": qa["question"]},
            outputs={"answer": qa["reference"]},
            metadata={"category": _get_category(qa["question"])},
        )
        for qa in SYNTHETIC_QUESTIONS
    ]

    client.create_examples(dataset_id=dataset.id, examples=examples)
    print(f"Created dataset '{dataset_name}' with {len(examples)} examples. ID: {dataset.id}")

    return str(dataset.id)


def _get_category(question: str) -> str:
    """Categorize a question based on keywords."""
    lower = question.lower()
    if any(w in lower for w in ["summarize", "explain", "describe", "what are"]):
        return "abstractive"
    if any(w in lower for w in ["which", "more", "larger", "farther", "if"]):
        return "multi-hop"
    if any(w in lower for w in ["meaning of life", "dark matter", "quantum", "agi", "artificial general"]):
        return "edge-case"
    return "factual"
```

---

## 3. Running RAGAS Evaluation

```python
from langsmith import Client
from ragas import evaluate, EvaluationDataset, SingleTurnSample
from ragas.metrics import faithfulness, context_recall, answer_relevancy
from ragas.llms import LangchainLLMWrapper
from langchain_openai import ChatOpenAI
import json

client = Client()


async def run_ragas_evaluation(
    dataset_id: str,
    experiment_name: str = "rag-studio-eval-run",
    target_function=None,  # your RAG pipeline function
) -> dict:
    """Run RAGAS evaluation on a LangSmith dataset.

    Args:
        dataset_id: The LangSmith dataset ID.
        experiment_name: Name for the experiment run.
        target_function: Async function that takes (question: str) -> (answer: str, contexts: list[str]).

    Returns:
        Dict with metric scores and experiment URL.
    """
    # Load dataset examples
    examples = list(client.list_examples(dataset_id=dataset_id))

    # Build RAGAS evaluation samples
    eval_samples = []
    for ex in examples:
        question = ex.inputs["question"]
        reference = ex.outputs["answer"]

        # Run the target RAG pipeline
        if target_function:
            answer, contexts = await target_function(question)
        else:
            # Fallback: run against actual RAG-Studio endpoint
            answer, contexts = await run_rag_studio(question)

        eval_samples.append(
            SingleTurnSample(
                user_input=question,
                response=answer,
                reference=reference,
                retrieved_contexts=contexts,
            )
        )

    # Create RAGAS evaluation dataset
    eval_dataset = EvaluationDataset(samples=eval_samples)

    # Configure LLM for RAGAS metrics (uses LangSmith tracing automatically)
    evaluator_llm = LangchainLLMWrapper(ChatOpenAI(model="gpt-4o-mini", temperature=0))

    # Run evaluation
    result = evaluate(
        dataset=eval_dataset,
        metrics=[
            faithfulness,
            context_recall,
            answer_relevancy,
        ],
        llm=evaluator_llm,
        run_config={
            "run_name": experiment_name,
            "project_name": "rag-studio-eval",
        },
    )

    # Parse results
    scores = {
        "faithfulness": float(result["faithfulness"]),
        "context_recall": float(result["context_recall"]),
        "answer_relevancy": float(result["answer_relevancy"]),
    }

    print(json.dumps(scores, indent=2))
    return scores


async def run_rag_studio(question: str) -> tuple[str, list[str]]:
    """Run a question through the RAG-Studio pipeline.

    Replace with actual FastAPI call or direct graph invocation.
    """
    import aiohttp

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "http://localhost:8000/chat",
            json={"query": question, "session_id": "eval-session"},
        ) as resp:
            data = await resp.json()
            return data["answer"], data.get("contexts", [])
```

---

## 4. Parsing Experiment Results and Checking Thresholds

```python
def check_ragas_thresholds(scores: dict) -> dict:
    """Check if RAGAS scores meet project thresholds.

    Thresholds from copilot-instructions.md:
    - faithfulness > 0.7
    - context_recall > 0.8
    - answer_relevancy > 0.7
    """
    thresholds = {
        "faithfulness": 0.7,
        "context_recall": 0.8,
        "answer_relevancy": 0.7,
    }

    results = {}
    all_pass = True

    for metric, threshold in thresholds.items():
        score = scores.get(metric, 0.0)
        passed = score > threshold
        results[metric] = {
            "score": score,
            "threshold": threshold,
            "passed": passed,
            "delta": round(score - threshold, 4),
        }
        if not passed:
            all_pass = False

    return {
        "overall": "PASS" if all_pass else "FAIL",
        "metrics": results,
    }


# Example usage:
# scores = await run_ragas_evaluation(dataset_id="...", target_function=my_rag_fn)
# threshold_check = check_ragas_thresholds(scores)
# print(json.dumps(threshold_check, indent=2))
```

---

## 5. Complete Evaluation Runner (CLI-ready)

```python
import asyncio
import sys


async def main():
    """Full evaluation runner — creates dataset, runs RAGAS, checks thresholds."""
    # Step 1: Create/find dataset
    dataset_id = create_eval_dataset()
    print(f"\n📊 Dataset: {dataset_id}")

    # Step 2: Run RAGAS evaluation
    print("\n🔄 Running RAGAS evaluation...")
    scores = await run_ragas_evaluation(
        dataset_id=dataset_id,
        experiment_name=f"rag-studio-eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
    )

    # Step 3: Check thresholds
    print("\n📋 Threshold Check:")
    results = check_ragas_thresholds(scores)
    print(json.dumps(results, indent=2))

    # Step 4: Exit with appropriate code
    if results["overall"] == "PASS":
        print("\n✅ All RAGAS thresholds met!")
        sys.exit(0)
    else:
        print("\n❌ Some RAGAS thresholds NOT met. See details above.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 6. Expected Output Format (for QA_VERDICT)

When invoked by @qa, return scores in this format:

```json
{
  "ragasScores": {
    "faithfulness": 0.85,
    "context_recall": 0.92,
    "answer_relevancy": 0.78
  },
  "thresholdsMet": {
    "faithfulness": true,
    "context_recall": true,
    "answer_relevancy": true
  },
  "overallRagasVerdict": "PASS",
  "experimentUrl": "https://smith.langchain.com/o/.../experiments/..."
}
```

---

## Best Practices

1. **Create the dataset ONCE, reuse it** — the 40 questions should be checked into the repo or created once in LangSmith.
2. **Use `gpt-4o-mini` as the RAGAS evaluator LLM** — cheaper and sufficient for metric computation.
3. **Always include `reference` answers** in the dataset for faithfulness comparison.
4. **Run evaluations idempotently** — same dataset, same code → reproducible results.
5. **Store experiment URLs** in QA_VERDICT for traceability.
6. **Fail CI if thresholds not met** — use exit code 1.
