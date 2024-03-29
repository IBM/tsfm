# Copyright contributors to the TSFM project
#
"""Hugging Face Pipeline for Time Series Tasks"""

import inspect
from typing import Any, Dict, List, Optional, Union

import pandas as pd
import torch
from transformers.pipelines.base import (
    GenericTensor,
    Pipeline,
    build_pipeline_init_args,
)
from transformers.utils import add_end_docstrings, logging

from .dataset import ForecastDFDataset
from .time_series_preprocessor import create_timestamps, extend_time_series


# Eventually we should support all time series models
# MODEL_FOR_TIME_SERIES_FORECASTING_MAPPING_NAMES = OrderedDict(
#     [
#         # Model for Time Series Forecasting
#         ("PatchTST", "PatchTSTForPrediction"),
#         ("TST", "TimeSeriesTransformerForPrediction"),
#     ]
# )


logger = logging.get_logger(__name__)


@add_end_docstrings(
    build_pipeline_init_args(has_tokenizer=False, has_feature_extractor=True, has_image_processor=False)
)
class TimeSeriesForecastingPipeline(Pipeline):
    """Hugging Face Pipeline for Time Series Forecasting"""

    # has_feature_extractor means we can pass feature_extractor=TimeSeriesPreprocessor

    def __init__(
        self,
        *args,
        explode_forecasts: bool = False,
        freq: Optional[Union[Any]] = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        if self.framework == "tf":
            raise ValueError(f"The {self.__class__} is only available in PyTorch.")

        self.explode_forecasts = explode_forecasts
        self.freq = freq
        # self.check_model_type(MODEL_FOR_TIME_SERIES_FORECASTING_MAPPING)

    def _sanitize_parameters(self, **kwargs):
        """Assign parameters to the different parts of the process.

        For expected parameters see the call method below.
        """

        context_length = kwargs.get("context_length", self.model.config.context_length)
        prediction_length = kwargs.get("prediction_length", self.model.config.prediction_length)

        preprocess_kwargs = {
            "prediction_length": prediction_length,
            "context_length": context_length,
        }
        postprocess_kwargs = {
            "prediction_length": prediction_length,
            "context_length": context_length,
        }

        preprocess_params = [
            "id_columns",
            "timestamp_column",
            "target_columns",
            "observable_columns",
            "control_columns",
            "conditional_columns",
            "static_categorical_columns",
            "future_time_series",
        ]
        postprocess_params = [
            "id_columns",
            "timestamp_column",
            "target_columns",
            "observable_columns",
            "control_columns",
            "conditional_columns",
            "static_categorical_columns",
        ]

        for c in preprocess_params:
            if c in kwargs:
                preprocess_kwargs[c] = kwargs[c]

        for c in postprocess_params:
            if c in kwargs:
                postprocess_kwargs[c] = kwargs[c]

        # if "id_columns" in kwargs:
        #     preprocess_kwargs["id_columns"] = kwargs["id_columns"]
        #     postprocess_kwargs["id_columns"] = kwargs["id_columns"]
        # if "timestamp_column" in kwargs:
        #     preprocess_kwargs["timestamp_column"] = kwargs["timestamp_column"]
        #     postprocess_kwargs["timestamp_column"] = kwargs["timestamp_column"]
        # if "input_columns" in kwargs:
        #     preprocess_kwargs["input_columns"] = kwargs["input_columns"]
        #     postprocess_kwargs["input_columns"] = kwargs["input_columns"]
        # if "output_columns" in kwargs:
        #     preprocess_kwargs["output_columns"] = kwargs["output_columns"]
        #     postprocess_kwargs["output_columns"] = kwargs["output_columns"]
        # elif "input_columns" in kwargs:
        #     preprocess_kwargs["output_columns"] = kwargs["input_columns"]
        #     postprocess_kwargs["output_columns"] = kwargs["input_columns"]

        return preprocess_kwargs, {}, postprocess_kwargs

    def __call__(
        self,
        time_series: Union["pd.DataFrame", str],
        **kwargs,
    ):
        """Main method of the forecasting pipeline. Takes the input time series data (in tabular format) and
        produces predictions.

        Args:
            time_series (Union[&quot;pandas.DataFrame&quot;, str]): A pandas dataframe or a referce to a location
            from where a pandas datarame can be loaded containing the time series on which to perform inference.

            future_time_series (Union[&quot;pandas.DataFrame&quot;, str]): A pandas dataframe or a referce to a location
            from where a pandas datarame can be loaded containing future values, i.e., exogenous or supporting features
            which are known in advance.

            To do: describe batch vs. single and the need for future_time_series


            kwargs

            future_time_series: Optional[Union["pandas.DataFrame", str]] = None,
            prediction_length
            context_length

            timestamp_column (str): the column containing the date / timestamp
            id_columns (List[str]): the list of columns containing ID information. If no ids are present, pass [].

            "target_columns",
            "observable_columns",
            "control_columns",
            "conditional_columns",
            "static_categorical_columns",


            # OLD
            input_columns (List[str]): the columns that are used as to create the inputs to the forecasting model.
            These values are used to select data in the input dataframe.
            output_columns (List[str]): the column names that are used to label the outputs of the forecasting model.
            If omitted, it is assumed that the model will forecast values for all the input columns.


            Return:
            A new pandas dataframe containing the forecasts. Each row will contain the id, timestamp, the original
            input feature values and the output forecast for each input column. The output forecast is a list containing
            all the values over the prediction horizon.

        """

        return super().__call__(time_series, **kwargs)

    def preprocess(self, time_series, **kwargs) -> Dict[str, Union[GenericTensor, List[Any]]]:
        """Preprocess step
        Load the data, if not already loaded, and then generate a pytorch dataset.
        """

        prediction_length = kwargs.get("prediction_length")
        timestamp_column = kwargs.get("timestamp_column")
        id_columns = kwargs.get("id_columns")
        # context_length = kwargs.get("context_length")

        if isinstance(time_series, str):
            time_series = pd.read_csv(
                time_series,
                parse_dates=[timestamp_column],
            )

        future_time_series = kwargs.pop("future_time_series", None)

        if future_time_series is not None:
            if isinstance(future_time_series, str):
                future_time_series = pd.read_csv(
                    future_time_series,
                    parse_dates=[timestamp_column],
                )
            elif isinstance(future_time_series, pd.DataFrame):
                # do we need to check the timestamp column?
                pass
            else:
                raise ValueError(f"`future_time_series` of type {type(future_time_series)} is not supported.")

            # stack the time series
            for c in future_time_series.columns:
                if c not in time_series.columns:
                    raise ValueError(f"Future time series input contains an unknown column {c}.")

            time_series = pd.concat((time_series, future_time_series), axis=0)
        else:
            # no additional exogenous data provided, extend with empty periods
            time_series = extend_time_series(
                time_series=time_series,
                timestamp_column=timestamp_column,
                grouping_columns=id_columns,
                periods=prediction_length,
            )

        # use forecasing dataset to do the preprocessing
        dataset = ForecastDFDataset(
            time_series,
            **kwargs,
        )

        # stack all the outputs
        # torch tensors are stacked, but other values are passed through as a list
        first = dataset[0]
        full_output = {}
        for k, v in first.items():
            if isinstance(v, torch.Tensor):
                full_output[k] = torch.stack(tuple(r[k] for r in dataset))
            else:
                full_output[k] = [r[k] for r in dataset]

        return full_output

    def _forward(self, model_inputs, **kwargs):
        """Forward step
        Responsible for taking pre-processed dictionary of tensors and passing it to
        the model. Aligns model parameters with the proper input parameters. Only passes
        the needed parameters from the dictionary to the model, but adds them back to the
        ouput for the next step.

        The keys in model_outputs are governed by the underlying model combined with any
        original input keys.
        """

        # Eventually we should use inspection somehow
        # inspect.signature(model_forward).parameters.keys()
        # model_input_keys = {
        #     "past_values",
        #     "static_categorical_values",
        #     "freq_token",
        # }  # todo: this should not be hardcoded

        signature = inspect.signature(self.model.forward)
        model_input_keys = list(signature.parameters.keys())

        model_inputs_only = {}
        for k in model_input_keys:
            if k in model_inputs:
                model_inputs_only[k] = model_inputs[k]

        model_outputs = self.model(**model_inputs_only)

        # copy the other inputs
        copy_inputs = True
        for k in [akey for akey in model_inputs.keys() if (akey not in model_input_keys) or copy_inputs]:
            model_outputs[k] = model_inputs[k]

        return model_outputs

    def postprocess(self, input, **kwargs):
        """Postprocess step
        Takes the dictionary of outputs from the previous step and converts to a more user
        readable pandas format.
        """
        out = {}

        model_output_key = "prediction_outputs" if "prediction_outputs" in input.keys() else "prediction_logits"

        # name the predictions of target columns
        # outputs should only have size equal to target columns
        prediction_columns = []
        for i, c in enumerate(kwargs["target_columns"]):
            prediction_columns.append(f"{c}_prediction")
            out[prediction_columns[-1]] = input[model_output_key][:, :, i].numpy().tolist()
        # provide the ground truth values for the targets
        # when future is unknown, we will have augmented the provided dataframe with NaN values to cover the future
        for i, c in enumerate(kwargs["target_columns"]):
            out[c] = input["future_values"][:, :, i].numpy().tolist()

        if "timestamp_column" in kwargs:
            out[kwargs["timestamp_column"]] = input["timestamp"]
        for i, c in enumerate(kwargs["id_columns"]):
            out[c] = [elem[i] for elem in input["id"]]
        out = pd.DataFrame(out)

        if self.explode_forecasts:
            # we made only one forecast per time series, explode results
            # explode == expand the lists in the dataframe
            out_explode = []
            for _, row in out.iterrows():
                l = len(row[prediction_columns[0]])
                tmp = {}
                if "timestamp_column" in kwargs:
                    tmp[kwargs["timestamp_column"]] = create_timestamps(
                        row[kwargs["timestamp_column"]], freq=self.freq, periods=l
                    )  # expand timestamps
                if "id_columns" in kwargs:
                    for c in kwargs["id_columns"]:
                        tmp[c] = row[c]
                for p in prediction_columns:
                    tmp[p] = row[p]

                out_explode.append(pd.DataFrame(tmp))

            out = pd.concat(out_explode)

        # reorder columns
        cols = out.columns.to_list()
        cols_ordered = []
        if "timestamp_column" in kwargs:
            cols_ordered.append(kwargs["timestamp_column"])
        if "id_columns" in kwargs:
            cols_ordered.extend(kwargs["id_columns"])
        cols_ordered.extend([c for c in cols if c not in cols_ordered])

        out = out[cols_ordered]
        return out
