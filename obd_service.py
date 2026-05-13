import obd

PORT = "COM11"
BAUDRATE = 38400

connection = obd.OBD(
    portstr=PORT,
    baudrate=BAUDRATE,
    fast=False,
    timeout=30,
)


def is_connected():
    return connection.is_connected()


def safe_query(command):
    try:
        response = connection.query(command)
        if response is None or response.is_null():
            return None
        return response.value
    except Exception:
        return None


def clean_vin(v):
    if v is None:
        return "VIN unavailable"
    text = str(v)
    if "bytearray" in text and "\\xff" in text:
        return "VIN unavailable"
    return text


def get_vin():
    if not connection.is_connected():
        return "VIN unavailable"
    return clean_vin(safe_query(obd.commands.VIN))


def get_sample():
    if not connection.is_connected():
        return None

    return {
        "speed": safe_query(obd.commands.SPEED),
        "rpm": safe_query(obd.commands.RPM),
        "coolant_temp": safe_query(obd.commands.COOLANT_TEMP),
        "intake_air_temp": safe_query(obd.commands.INTAKE_TEMP),
        "throttle_pos": safe_query(obd.commands.THROTTLE_POS),
        "maf": safe_query(obd.commands.MAF),
        "engine_load": safe_query(obd.commands.ENGINE_LOAD),
        "control_module_voltage": safe_query(obd.commands.CONTROL_MODULE_VOLTAGE),
    }