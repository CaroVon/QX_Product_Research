import re

from app.planner.outline_generator import generate_outline
from app.report.section_writer import write_section
from app.report.markdown_formatter import build_report
from app.report.pdf_generator import markdown_to_pdf

from app.rag.rag_pipeline import build_knowledge_base


def extract_sections(outline: str):

    lines = outline.split("\n")

    sections = []

    for line in lines:

        line = line.strip()

        if line.startswith("##"):
            title = re.sub(r"^##\s*", "", line)
            sections.append(title)

    return sections


def run_workflow(topic: str):

    print("\n[1] Building knowledge base...\n")

    build_knowledge_base(topic)

    print("\n[2] Generating outline...\n")

    outline = generate_outline(topic)

    print(outline)

    section_titles = extract_sections(outline)

    completed_sections = []

    for section in section_titles:

        print(f"\n[3] Writing section: {section}\n")

        content = write_section(
            topic,
            section
        )

        completed_sections.append(content)

    print("\n[4] Building final report...\n")

    report = build_report(topic, completed_sections)

    output_path = f"outputs/v2(citation)_{topic}_report.md"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\n[OK] Report saved to: {output_path}")

    pdf_output_path = f"outputs/v2(citation)_{topic}_report.pdf"

    markdown_to_pdf(
        output_path,
        pdf_output_path
    )

    print(f"\n[OK] PDF saved to: {pdf_output_path}")


if __name__ == "__main__":

    topic = "宋代青瓷元素新国潮软床" 

    run_workflow(topic)