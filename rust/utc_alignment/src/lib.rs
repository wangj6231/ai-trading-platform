#![forbid(unsafe_code)]

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use serde::de::{self, SeqAccess, Visitor};
use serde::{Deserialize, Deserializer, Serialize};
use std::fmt;
use std::panic::{catch_unwind, UnwindSafe};

const MAX_ITEMS: usize = 4096;
const MAX_BATCH_SIZE: usize = MAX_ITEMS;
const MAX_INPUT_BYTES: usize = 131_072;
const MAX_OUTPUT_BYTES: usize = 256;
const MIN_TIMESTAMP_US: i64 = -62_135_596_800_000_000;
const MAX_TIMESTAMP_US: i64 = 253_402_300_799_999_999;

// Fixed storage: serde never allocates a provider-sized Vec of timestamps.
struct Timestamps {
    values: [i64; MAX_BATCH_SIZE],
    len: usize,
}

impl<'de> Deserialize<'de> for Timestamps {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct BoundedVisitor;
        impl<'de> Visitor<'de> for BoundedVisitor {
            type Value = Timestamps;
            fn expecting(&self, formatter: &mut fmt::Formatter) -> fmt::Result {
                formatter.write_str("bounded timestamp array")
            }
            fn visit_seq<A: SeqAccess<'de>>(self, mut sequence: A) -> Result<Timestamps, A::Error> {
                let mut result = Timestamps {
                    values: [0; MAX_BATCH_SIZE],
                    len: 0,
                };
                while let Some(value) = sequence.next_element::<i64>()? {
                    if result.len == MAX_BATCH_SIZE {
                        return Err(de::Error::custom("INVALID_INPUT"));
                    }
                    result.values[result.len] = value;
                    result.len += 1;
                }
                Ok(result)
            }
        }
        deserializer.deserialize_seq(BoundedVisitor)
    }
}

#[derive(Deserialize)]
enum ContractVersion {
    #[serde(rename = "1")]
    V1,
}

#[derive(Deserialize)]
enum Timeframe {
    #[serde(rename = "1m")]
    M1,
    #[serde(rename = "3m")]
    M3,
    #[serde(rename = "5m")]
    M5,
    #[serde(rename = "15m")]
    M15,
    #[serde(rename = "30m")]
    M30,
    #[serde(rename = "1h")]
    H1,
    #[serde(rename = "2h")]
    H2,
    #[serde(rename = "4h")]
    H4,
    #[serde(rename = "1d")]
    D1,
    #[serde(rename = "1w")]
    W1,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RustComputeInputV1 {
    contract_version: ContractVersion,
    timeframe: Timeframe,
    timestamps_us: Timestamps,
}

#[derive(Serialize)]
struct RustComputeOutputV1 {
    contract_version: &'static str,
    first_misaligned_index: Option<usize>,
    item_count: usize,
}

fn evaluate(input: &[u8]) -> Result<Vec<u8>, &'static str> {
    if input.len() > MAX_INPUT_BYTES {
        return Err("INPUT_TOO_LARGE");
    }
    let value: RustComputeInputV1 = serde_json::from_slice(input).map_err(|_| "INVALID_INPUT")?;
    let ContractVersion::V1 = value.contract_version;
    if value.timestamps_us.values[..value.timestamps_us.len]
        .iter()
        .any(|x| !(MIN_TIMESTAMP_US..=MAX_TIMESTAMP_US).contains(x))
    {
        return Err("INVALID_INPUT");
    }
    let (interval, offset): (i64, i64) = match value.timeframe {
        Timeframe::M1 => (60_000_000, 0),
        Timeframe::M3 => (180_000_000, 0),
        Timeframe::M5 => (300_000_000, 0),
        Timeframe::M15 => (900_000_000, 0),
        Timeframe::M30 => (1_800_000_000, 0),
        Timeframe::H1 => (3_600_000_000, 0),
        Timeframe::H2 => (7_200_000_000, 0),
        Timeframe::H4 => (14_400_000_000, 0),
        Timeframe::D1 => (86_400_000_000, 0),
        Timeframe::W1 => (604_800_000_000, 259_200_000_000),
    };
    let first = value.timestamps_us.values[..value.timestamps_us.len]
        .iter()
        .position(|timestamp| (timestamp + offset).rem_euclid(interval) != 0);
    // Only a fixed three-field result is serialized; allocation is independent of input count.
    let output = serde_json::to_vec(&RustComputeOutputV1 {
        contract_version: "1",
        first_misaligned_index: first,
        item_count: value.timestamps_us.len,
    })
    .map_err(|_| "INTERNAL_ERROR")?;
    if output.len() > MAX_OUTPUT_BYTES {
        return Err("OUTPUT_TOO_LARGE");
    }
    Ok(output)
}

fn guarded<T>(
    operation: impl FnOnce() -> Result<T, &'static str> + UnwindSafe,
) -> Result<T, &'static str> {
    catch_unwind(operation).map_err(|_| "INTERNAL_ERROR")?
}

#[pyfunction]
fn align_v1<'py>(py: Python<'py>, payload: &[u8]) -> PyResult<Bound<'py, PyBytes>> {
    let output = guarded(|| evaluate(payload)).map_err(PyValueError::new_err)?;
    Ok(PyBytes::new(py, &output))
}

#[pymodule]
fn _utc_alignment_core(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(align_v1, module)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canonical_empty_output() {
        let result = evaluate(br#"{"contract_version":"1","timeframe":"1m","timestamps_us":[]}"#);
        assert_eq!(
            result.as_deref(),
            Ok(
                br#"{"contract_version":"1","first_misaligned_index":null,"item_count":0}"#
                    .as_slice()
            )
        );
    }

    #[test]
    fn first_misaligned_index_is_stable() {
        let result =
            evaluate(br#"{"contract_version":"1","timeframe":"1m","timestamps_us":[0,1,2]}"#);
        assert_eq!(
            result.as_deref(),
            Ok(br#"{"contract_version":"1","first_misaligned_index":1,"item_count":3}"#.as_slice())
        );
    }

    #[test]
    fn weekly_is_iso_monday_including_negative_epoch() {
        let result = evaluate(br#"{"contract_version":"1","timeframe":"1w","timestamps_us":[-259200000000,345600000000]}"#);
        assert_eq!(
            result.as_deref(),
            Ok(
                br#"{"contract_version":"1","first_misaligned_index":null,"item_count":2}"#
                    .as_slice()
            )
        );
    }

    #[test]
    fn unknown_duplicate_and_trailing_fields_fail() {
        for raw in [
            br#"{"contract_version":"1","timeframe":"1m","timestamps_us":[],"unknown":"private"}"#
                .as_slice(),
            br#"{"contract_version":"1","timeframe":"1m","timeframe":"3m","timestamps_us":[]}"#
                .as_slice(),
            br#"{"contract_version":"1","timeframe":"1m","timestamps_us":[]} {}"#.as_slice(),
            br#"{"contract_version":"2","timeframe":"1m","timestamps_us":[]}"#.as_slice(),
        ] {
            assert_eq!(evaluate(raw), Err("INVALID_INPUT"));
        }
    }

    #[test]
    fn item_cap_has_no_growing_timestamp_storage() {
        for count in [MAX_ITEMS, MAX_ITEMS + 1] {
            let raw = format!(
                "{{\"contract_version\":\"1\",\"timeframe\":\"1m\",\"timestamps_us\":[{}]}}",
                vec!["0"; count].join(",")
            );
            if count == MAX_ITEMS {
                assert!(evaluate(raw.as_bytes()).is_ok());
            } else {
                assert_eq!(evaluate(raw.as_bytes()), Err("INVALID_INPUT"));
            }
        }
    }

    #[test]
    fn byte_cap_precedes_parsing() {
        assert_eq!(
            evaluate(&vec![b' '; MAX_INPUT_BYTES + 1]),
            Err("INPUT_TOO_LARGE")
        );
    }

    #[test]
    fn invalid_integer_types_and_overflow_are_redacted() {
        for value in [
            "true",
            "null",
            "1.5",
            "9223372036854775808",
            "253402300800000000",
            "-62135596800000001",
        ] {
            let raw = format!(
                "{{\"contract_version\":\"1\",\"timeframe\":\"1m\",\"timestamps_us\":[{value}]}}"
            );
            assert_eq!(evaluate(raw.as_bytes()), Err("INVALID_INPUT"));
        }
    }

    #[test]
    fn panic_is_contained_and_returns_fixed_error() {
        let result: Result<(), &str> = guarded(|| panic!("controlled unit-test panic"));
        assert_eq!(result, Err("INTERNAL_ERROR"));
    }
}
