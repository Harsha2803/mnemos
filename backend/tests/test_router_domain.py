"""A4's deterministic, zero-cost message classifier."""

from mnemos.flows.router.domain import RouteFlow, classify_message


def test_obvious_assistant_questions_stay_in_plain_chat() -> None:
    decision = classify_message("Explain why the sky appears blue")

    assert decision.flow is RouteFlow.CHAT
    assert decision.reason == "No document or database context is needed."


def test_document_and_citation_questions_route_to_rag() -> None:
    for question in (
        "According to the employee handbook, how much leave can I carry over?",
        "Summarise the report I uploaded",
        "Show the source citation for our policy",
    ):
        decision = classify_message(question)
        assert decision.flow is RouteFlow.RAG
        assert decision.reason == "Asks about documents or cited knowledge."


def test_structured_data_and_metric_questions_route_to_nl2sql() -> None:
    for question in (
        "What was total revenue by region last quarter?",
        "Which regions do we sell into?",
        "List the columns in the analytics.sales_order table",
    ):
        assert classify_message(question).flow is RouteFlow.NL2SQL


def test_a_write_like_data_request_still_routes_to_the_guarded_nl2sql_flow() -> None:
    decision = classify_message("Delete every region from the table")

    assert decision.flow is RouteFlow.NL2SQL
    assert decision.reason == "Mentions database or SQL concepts."


def test_document_vocabulary_wins_over_ambiguous_business_vocabulary() -> None:
    decision = classify_message("Summarise the quarterly sales report")

    assert decision.flow is RouteFlow.RAG


def test_classification_is_total_and_always_returns_display_safe_metadata() -> None:
    for content in ("", "   ", "こんにちは", "?" * 2_000, "customer", "uploaded SQL report"):
        decision = classify_message(content)

        assert decision.flow in RouteFlow
        assert 0 < len(decision.reason) <= 60
        assert "\n" not in decision.reason
