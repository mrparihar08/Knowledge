import React, { useCallback, useEffect, useMemo, useState } from "react";
import "./App.css";

const API_BASE_URL =
  (typeof import.meta !== "undefined" &&
    import.meta.env &&
    import.meta.env.VITE_API_URL) ||
  "https://knowledge-herl.onrender.com";

function App() {
  const [display, setDisplay] = useState("0");
  const [firstValue, setFirstValue] = useState(null);
  const [operator, setOperator] = useState(null);
  const [waitingForSecond, setWaitingForSecond] = useState(false);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const operatorMap = useMemo(
    () => ({
      "+": "add",
      "−": "subtract",
      "×": "multiply",
      "÷": "divide",
      "%": "percentage",
    }),
    []
  );

  const formatNumber = useCallback((value) => {
    if (
      typeof value !== "number" ||
      Number.isNaN(value) ||
      !Number.isFinite(value)
    ) {
      return "Error";
    }

    return String(Number(value.toFixed(10)));
  }, []);

  const resetError = useCallback(() => {
    setError("");
  }, []);

  const callBackend = useCallback(
    async (a, b, op) => {
      const operation = operatorMap[op];
      if (!operation) throw new Error("Invalid operation");

      const res = await fetch(`${API_BASE_URL}/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          num1: a,
          num2: b,
          operation,
        }),
      });

      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        throw new Error(data?.detail || "Calculation failed");
      }

      if (data?.result === undefined || data?.result === null) {
        throw new Error("Invalid backend response");
      }

      const resultNumber = Number(data.result);
      if (Number.isNaN(resultNumber)) {
        throw new Error("Invalid backend response");
      }

      return resultNumber;
    },
    [operatorMap]
  );

  const clearDisplay = useCallback(() => {
    setDisplay("0");
    setFirstValue(null);
    setOperator(null);
    setWaitingForSecond(false);
    setError("");
    setIsLoading(false);
  }, []);

  const inputNumber = useCallback(
    (num) => {
      resetError();

      if (display === "Error") {
        setDisplay(num);
        return;
      }

      if (waitingForSecond) {
        setDisplay(num);
        setWaitingForSecond(false);
        return;
      }

      setDisplay((prev) => (prev === "0" ? num : prev + num));
    },
    [display, waitingForSecond, resetError]
  );

  const inputDecimal = useCallback(() => {
    resetError();

    if (display === "Error") {
      setDisplay("0.");
      return;
    }

    if (waitingForSecond) {
      setDisplay("0.");
      setWaitingForSecond(false);
      return;
    }

    setDisplay((prev) => (prev.includes(".") ? prev : prev + "."));
  }, [display, waitingForSecond, resetError]);

  const deleteDigit = useCallback(() => {
    resetError();

    if (display === "Error" || waitingForSecond) {
      setDisplay("0");
      setWaitingForSecond(false);
      return;
    }

    if (display.length === 1 || (display.length === 2 && display.startsWith("-"))) {
      setDisplay("0");
      return;
    }

    setDisplay((prev) => prev.slice(0, -1));
  }, [display, waitingForSecond, resetError]);

  const handleOperator = useCallback(
    async (nextOperator) => {
      resetError();

      const inputValue = parseFloat(display);
      if (Number.isNaN(inputValue)) {
        setError("Invalid number");
        setDisplay("Error");
        return;
      }

      if (firstValue === null) {
        setFirstValue(inputValue);
        setOperator(nextOperator);
        setWaitingForSecond(true);
        return;
      }

      if (operator && !waitingForSecond) {
        setIsLoading(true);
        try {
          const result = await callBackend(firstValue, inputValue, operator);
          const formatted = formatNumber(result);

          if (formatted === "Error") {
            setDisplay("Error");
            setError("Invalid calculation");
            setFirstValue(null);
            setOperator(null);
            setWaitingForSecond(false);
            return;
          }

          setDisplay(formatted);
          setFirstValue(result);
        } catch (err) {
          setDisplay("Error");
          setError(err?.message || "Backend unavailable");
          setFirstValue(null);
          setOperator(null);
          setWaitingForSecond(false);
          return;
        } finally {
          setIsLoading(false);
        }
      }

      setOperator(nextOperator);
      setWaitingForSecond(true);
    },
    [display, firstValue, operator, waitingForSecond, callBackend, formatNumber, resetError]
  );

  const handleEqual = useCallback(async () => {
    if (!operator || firstValue === null) return;

    const inputValue = parseFloat(display);
    if (Number.isNaN(inputValue)) {
      setError("Invalid number");
      setDisplay("Error");
      return;
    }

    setIsLoading(true);
    try {
      const result = await callBackend(firstValue, inputValue, operator);
      const formatted = formatNumber(result);

      if (formatted === "Error") {
        setDisplay("Error");
        setError("Invalid calculation");
      } else {
        setDisplay(formatted);
      }

      setFirstValue(null);
      setOperator(null);
      setWaitingForSecond(true);
    } catch (err) {
      setDisplay("Error");
      setError(err?.message || "Backend unavailable");
      setFirstValue(null);
      setOperator(null);
      setWaitingForSecond(false);
    } finally {
      setIsLoading(false);
    }
  }, [operator, firstValue, display, callBackend, formatNumber]);

  useEffect(() => {
    const handleKeyPress = (e) => {
      if (e.key >= "0" && e.key <= "9") inputNumber(e.key);
      else if (e.key === ".") inputDecimal();
      else if (e.key === "+") handleOperator("+");
      else if (e.key === "-") handleOperator("−");
      else if (e.key === "*") handleOperator("×");
      else if (e.key === "/") handleOperator("÷");
      else if (e.key === "%") handleOperator("%");
      else if (e.key === "Enter") handleEqual();
      else if (e.key === "Backspace") deleteDigit();
      else if (e.key === "Escape") clearDisplay();
    };

    window.addEventListener("keydown", handleKeyPress);
    return () => window.removeEventListener("keydown", handleKeyPress);
  }, [inputNumber, inputDecimal, handleOperator, handleEqual, deleteDigit, clearDisplay]);

  return (
    <div className="container">
      <div className="calculator">
        <div className="header">
          <div>
            <h1>Calculator</h1>
            <p>Backend only • Keyboard supported</p>
          </div>
          <button className="mini-button" onClick={clearDisplay} disabled={isLoading}>
            AC
          </button>
        </div>

        <div className="screen">
          <div className="operator-display">
            {isLoading ? "Calculating..." : operator || " "}
          </div>

          <div className={`display ${display === "Error" ? "error" : ""}`}>
            {display}
          </div>

          {error ? <div className="error-text">{error}</div> : null}
        </div>

        <div className="buttons">
          <button className="action" onClick={clearDisplay} disabled={isLoading}>
            AC
          </button>

          <button className="action" onClick={deleteDigit} disabled={isLoading}>
            ⌫
          </button>

          <button
            className="operator"
            onClick={() => handleOperator("%")}
            disabled={isLoading}
          >
            %
          </button>

          <button
            className="operator"
            onClick={() => handleOperator("÷")}
            disabled={isLoading}
          >
            ÷
          </button>

          <button onClick={() => inputNumber("7")} disabled={isLoading}>7</button>
          <button onClick={() => inputNumber("8")} disabled={isLoading}>8</button>
          <button onClick={() => inputNumber("9")} disabled={isLoading}>9</button>

          <button
            className="operator"
            onClick={() => handleOperator("×")}
            disabled={isLoading}
          >
            ×
          </button>

          <button onClick={() => inputNumber("4")} disabled={isLoading}>4</button>
          <button onClick={() => inputNumber("5")} disabled={isLoading}>5</button>
          <button onClick={() => inputNumber("6")} disabled={isLoading}>6</button>

          <button
            className="operator"
            onClick={() => handleOperator("−")}
            disabled={isLoading}
          >
            −
          </button>

          <button onClick={() => inputNumber("1")} disabled={isLoading}>1</button>
          <button onClick={() => inputNumber("2")} disabled={isLoading}>2</button>
          <button onClick={() => inputNumber("3")} disabled={isLoading}>3</button>

          <button
            className="operator"
            onClick={() => handleOperator("+")}
            disabled={isLoading}
          >
            +
          </button>

          <button className="zero" onClick={() => inputNumber("0")} disabled={isLoading}>
            0
          </button>

          <button onClick={inputDecimal} disabled={isLoading}>
            .
          </button>

          <button className="equal" onClick={handleEqual} disabled={isLoading}>
            =
          </button>
        </div>
      </div>
    </div>
  );
}

export default App;