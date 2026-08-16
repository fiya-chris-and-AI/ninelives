# Islanding: How Power Grids Contain Their Own Failures

When a fault occurs somewhere on an electrical grid, a short circuit, a
downed line, a failed transformer, the grid's protective relays do not try
to keep the whole network running through it. They deliberately fragment the
grid into smaller, self-sufficient "islands" around the fault, each capable
of balancing its own local generation and demand independently, so the
failure is contained rather than propagating outward and collapsing the
entire interconnected system. This is the opposite instinct from what most
software architects reach for first, which is to keep every component
talking to every other component at all costs. Grid engineers learned the
hard way, most visibly in the 2003 Northeast blackout, that a fully
interconnected system with no ability to fragment gracefully turns a local
fault into a cascading, continent-scale failure within minutes. Deliberate
partition tolerance, not maximal connectivity, is what kept later, similar
faults from becoming similar blackouts.
