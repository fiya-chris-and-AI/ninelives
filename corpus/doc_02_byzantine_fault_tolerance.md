# Byzantine Fault Tolerance in Distributed Databases

A distributed database that must keep answering correctly even when some of
its own nodes fail, lie, or disappear is solving a problem first formalized
as the Byzantine Generals Problem: how do you reach agreement when you cannot
fully trust every participant to report honestly or promptly? Modern
consensus protocols such as Raft and Paxos solve a weaker but still hard
version of this problem, tolerating crashed or slow nodes rather than
malicious ones, by requiring a quorum, a strict majority of replicas, to
agree before any write is considered committed. This is why a three-node
cluster can survive the loss of one node without losing data or availability,
and why a five-node cluster can survive two: the surviving majority always
outnumbers whatever is missing. The mind of the system, in effect, lives in
the quorum, not in any single node.
