# literenare

## Goal

The goal with this project is to develop an AI-focused API backend for the it42 project. 

This backend filters and serves suggestions, streamlining the user experience for grantees, granters and other people on the platform.

## Technical Decisions:

 - Use JeV-style models in order to get quick ordering and a point based matching.
 - Use open-weighted models only.
 - Using traditional Large Language Models (LLMs) only in order to perform more complex tasks.

## Platform

 - Lang: Python
 - Compatible with OpenAI-style endpoints
 - Configurable API base prompts, concurrency, endpoints and keys.

## Future Choices

 - Using in-house models to increase accuracy
 - Context-aware translation in order to ensure accuracy along the whole chain
	- Open-weighted JeV models are primarily trained in English.
	- Make the whole chain English, using e.g. Translategemma in the beginning and end.
	- (IN) Swedish -> (AI Processing) English -> (OUT) Swedish

# Hurdles

 - Conflict of Interest
 - Matching fields 


