# Triple Modular Redundancy: Computing Where No One Can Fly Out to Fix It

The Apollo Guidance Computer and, decades later, the flight computers on the
Voyager probes solved the same problem from opposite ends of the reliability
spectrum: how do you trust a computation when you cannot send a technician to
repair the hardware if it glitches. Triple modular redundancy runs the same
computation on three independent processors simultaneously and takes the
majority vote of their outputs, so a single processor corrupted by anything
from a cosmic ray bit-flip to a manufacturing defect is simply outvoted and
never affects the result. Voyager 1 and 2, launched in 1977, are still
returning data from interstellar space using this principle, having long
outlived any engineer who could physically service them. The system does not
try to prevent individual failures, cosmic radiation guarantees that
individual bit-flips will happen, it treats disagreement between redundant
copies as the normal, expected signal that something failed, and routes
around it automatically.
