__all__ = [
    "PixTransactionAnalysisController",
    "PixTransactionController",
    "SampleEntityController",
]


def __getattr__(name: str):
    if name == "PixTransactionAnalysisController":
        from controllers.pix_transaction_analysis_controller import (
            PixTransactionAnalysisController,
        )

        return PixTransactionAnalysisController
    if name == "PixTransactionController":
        from controllers.pix_transaction_controller import PixTransactionController

        return PixTransactionController
    if name == "SampleEntityController":
        from controllers.sample_entity_controller import SampleEntityController

        return SampleEntityController
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
