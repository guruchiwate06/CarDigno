"""
CarDigno - SAE J1979 OBD-II Hexadecimal Stream Decoder
Decodes raw ELM327 ASCII/Hexadecimal telemetry into structured, typed time-series records.
"""

import logging
import time
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger("OBDDecoder")


class OBD2Decoder:
    """
    Decodes standard SAE J1979 OBD-II diagnostic response frames.
    
    Supported PIDs:
    - 010C: Engine RPM (Bytes: 2, Formula: ((A * 256) + B) / 4, Unit: RPM)
    - 0105: Engine Coolant Temp (Bytes: 1, Formula: A - 40, Unit: °C)
    - 0110: MAF Air Flow Rate (Bytes: 2, Formula: ((A * 256) + B) / 100, Unit: g/s)
    - 012F: Fuel Tank Level Input (Bytes: 1, Formula: (A * 100) / 255, Unit: %)
    """

    PID_SPECS = {
        "0C": {"pid": "010C", "metric_name": "RPM", "unit": "RPM", "bytes": 2},
        "05": {"pid": "0105", "metric_name": "Coolant_Temp", "unit": "°C", "bytes": 1},
        "10": {"pid": "0110", "metric_name": "MAF", "unit": "g/s", "bytes": 2},
        "2F": {"pid": "012F", "metric_name": "Fuel_Level", "unit": "%", "bytes": 1},
    }

    @classmethod
    def decode_line(cls, raw_line: str, timestamp: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """
        Decodes a single line from an ELM327 OBD-II data stream.
        Example raw_line inputs:
            '41 0C 1F 40'
            '41 05 7B\r'
            '41 10 05 DC\r\n'
            '41 2F C4'
        """
        if not raw_line:
            return None
        
        # Clean control characters and whitespace
        cleaned = raw_line.strip().replace("\r", " ").replace("\n", " ").strip()
        if not cleaned or cleaned.startswith(">") or cleaned.startswith("AT") or cleaned.startswith("OK"):
            return None
        
        tokens = cleaned.split()
        if len(tokens) < 3:
            return None
        
        # Mode 01 response identifier is 0x41
        mode_token = tokens[0].upper()
        if mode_token != "41":
            return None
        
        pid_token = tokens[1].upper()
        spec = cls.PID_SPECS.get(pid_token)
        if not spec:
            return None
        
        ts = timestamp if timestamp is not None else time.time()
        
        try:
            if pid_token == "0C":  # RPM: ((A * 256) + B) / 4
                if len(tokens) < 4:
                    return None
                a = int(tokens[2], 16)
                b = int(tokens[3], 16)
                decoded_val = ((a * 256.0) + b) / 4.0
                return {
                    "timestamp": ts,
                    "pid": "010C",
                    "metric_name": "RPM",
                    "decoded_value": round(decoded_val, 2),
                    "unit": "RPM",
                    "raw_hex": " ".join(tokens[:4])
                }
            
            elif pid_token == "05":  # Coolant Temp: A - 40
                a = int(tokens[2], 16)
                decoded_val = a - 40.0
                return {
                    "timestamp": ts,
                    "pid": "0105",
                    "metric_name": "Coolant_Temp",
                    "decoded_value": round(decoded_val, 2),
                    "unit": "°C",
                    "raw_hex": " ".join(tokens[:3])
                }
            
            elif pid_token == "10":  # MAF Air Flow Rate: ((A * 256) + B) / 100
                if len(tokens) < 4:
                    return None
                a = int(tokens[2], 16)
                b = int(tokens[3], 16)
                decoded_val = ((a * 256.0) + b) / 100.0
                return {
                    "timestamp": ts,
                    "pid": "0110",
                    "metric_name": "MAF",
                    "decoded_value": round(decoded_val, 2),
                    "unit": "g/s",
                    "raw_hex": " ".join(tokens[:4])
                }
            
            elif pid_token == "2F":  # Fuel Level: (A * 100) / 255
                a = int(tokens[2], 16)
                decoded_val = (a * 100.0) / 255.0
                return {
                    "timestamp": ts,
                    "pid": "012F",
                    "metric_name": "Fuel_Level",
                    "decoded_value": round(decoded_val, 2),
                    "unit": "%",
                    "raw_hex": " ".join(tokens[:3])
                }
        except (ValueError, IndexError) as e:
            logger.debug(f"Hex parsing failed for '{cleaned}': {e}")
            return None
        
        return None

    @classmethod
    def decode_stream_buffer(cls, buffer_text: str, timestamp: Optional[float] = None) -> Tuple[List[Dict[str, Any]], str]:
        """
        Processes a raw text buffer containing multiple or partial lines delimited by '\r' or '\n'.
        Returns:
            records: List of successfully decoded dictionary records
            remainder: Incomplete trailing line fragment to retain in buffer
        """
        if not buffer_text:
            return [], ""
        
        # Normalize carriage returns to newlines
        normalized = buffer_text.replace("\r\n", "\n").replace("\r", "\n")
        
        # If does not end with newline, last item is incomplete fragment
        if normalized.endswith("\n"):
            lines = normalized.split("\n")
            remainder = ""
        else:
            parts = normalized.split("\n")
            lines = parts[:-1]
            remainder = parts[-1]
            
        records = []
        for line in lines:
            decoded = cls.decode_line(line, timestamp=timestamp)
            if decoded:
                records.append(decoded)
                
        return records, remainder
