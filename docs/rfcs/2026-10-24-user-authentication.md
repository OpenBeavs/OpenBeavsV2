# RFC: [Authorization, Level of user athorization]

| Field | Value |
| --- | --- |
| Author | Pedro P Blanco Jaramillo |
| Date | 2026-10-24 |
| Status | Proposed |
| Decision Date | (fill when decided) |
| Deciders | Faith Nambasa, Jiya Pradhan, Dean R Leon, Pedro P Blanco Jaramillo, John V. Sweet |
| Superseded By | N/A |

## Problem and Context

OpenBeaves is a project that connects users to 'expert agents' through our harness. An 'expert agent' is an agent that is particularly very knowledgeable on one topic, such as about making a schedule, the college of engineering, or just general OSU information. This means that instead of how typical LLMs work where they are broadly knowledgeable, these expert agents will be maintained with data to make them very knowledgeable on one topic. Essentially, users first talk to Chris, who is the orchestrator. Chris will then take their question, analyze it, pass it off to the correct agent and respond with a response from an expert agent in our registry. If there is no expert agent then Chris will do their best to respond.

Due to this system's functionality, especially since it will act like a chatbot since many people have already gotten used to them, having an account would make sense to save chats. The old system did this by authenticating users with the same Microsoft SSO system that all students use. This would allow users to be able to sign-in and have their chats saved for later viewing. The issue is that the old systems database and backend need to change, meaning that the old authentication system is going to be updated a bit no matter what, while not even being MVP.

Therefore, we have to completely clarify what a full app might look like in the sense of authentication with a finished product, as even if authentication is not MVP right now, it could be something we want in the future. This is a feature that the longer it's not implemented the harder it could become to implement. This is why the decision needs to be made now while the backend and database is being redesigned.


## Options

### Option A: [Implement Microsoft SSO]

This option would mean to implement the Microsoft SSO as part of the MVP which would mean that the backend and database would need to be designed and implemented with Microsoft SSO in mind. By having this already implemented as part of the MVP we can have chat history and other user specific features more readily available to implement. The benefits are that we would future proof the current system as we will be building with having this authentication scheme in place making it easy to implement the user specific features in future as we will already have authorization done. The costs would be that we would need to plan for the integration of this system even though it's not in the scope of our current vision for MVP.

### Option B: [Design for Microsoft SSO]

This option would mean that we would not implement Microsoft SSO as part of the MVP but while building out parts of the MVP such as the database and backend we would design it around the idea that Microsoft SSO will be implemented at some point in the near future. The benefit of this option is that we would still be able to easily implement Microsoft SSO in the future, without going through the whole implementation process at this moment. This allows us to mainly work on MVP while still making future account specific features not as hard to implement due to building with the Microsoft SSO in mind. The cost of this is similar to the first option since we would need to build with it in mind, but it's not as much work allowing us to focus more on the MVP, though we would have more work later to implement the Microsoft SSO once we finish this MVP.

### Option C: Do Nothing

This option would mean that we do nothing when it comes to the authorization. We could simply focus on the MVP without worrying about implementing the Microsoft SSO at that moment and work to implement it at a later time. The benefit of this is that we can focus on MVP without any other features. The cost is that it could be more difficult to implement the Microsoft SSO at a later time and potentially delaying the addition of more account specific features since the database and backend might not have been designed with such future features in mind.

## Analysis

When considering option A, this would be the hardest option to do at this moment since it requires the most amount of work, but it would give us the best set up for future features, even though we don't need users to have user based features yet, like saved chats or pinned favorite expert agents. Then option C is the complete opposite which basically has the team fully work on MVP without worrying about implementing authentication, this would allow the team to finish MVP for the demo by maintaining complete focus on MVP features. The issue is that then the team can struggle to implement the user specific features later on. Finally, option c is a middle ground, we don't need to fully commit to implementing the Microsoft SSO but we just build towards our MVP goals with the authentication implementation in mind to make it easier later.

## Recommendation and Verification Plan

I propose that we do option B. Option C is too risky for future plans as it can make the future features difficult to implement. While option A is a better future proof option, the difficulty of this implementation depends on getting access to OSU’s Microsoft SSO, due to this it would be less risky to go for option B. By going for this option we can prepare for Microsoft SSO without fully implementing it, allowing us to quickly work on the MVP features without risking being able to implement the authentication later on. To know that this implementation choice worked we would know based on how we are able to implement Microsoft SSO when we need it. We can also actively test for it by writing code and reviewing our code with the idea that we will have it later. This way we stop each other from implementing code that is not friendly for a user system in the future.

## Constraints

This goes into the reason as to why going for option B is better, since going for option A and implementing Microsoft SSO in the future will require us to request access to OSU’s Microsoft SSO for us to use in our application. Depending on how this is done and how long the school takes to grant such a request this could be a long or quick procedure, though it's an unknown that we can't accurately quantify. Also, authentication is not required for MVP so it's not something that we need to be completely capable to implement at this moment. By having authentication and doing things such as saving chats which could contain personal user information, we would also need to guarantee that everything is private and secure to our users.

## Delegation and Validation

- **What you handed to AI tools** Generative AI handled an analysis of the codebase that was handed to us, and in the context of authentication it gave examples of where the old authentication could be difficult to pass over to the new repo.
- **What checks made that reasonable**: The old repo had a test that made sure that the system worked a certain way, but also the AI did not make any changes to the repo and just read over files to identify concerning points in the repo.
- **Where you stopped and validated the result yourself, and why those points.** I personally checked things like the Microsoft SSO transfer process to our new repo to projects and systems we would need in place in our new backend and database to make sure that it worked. Due to this is why I came to the conclusion of the three different options that we had to implement authentication at this time.

## Decision

Proposed, until your team decides. Then accepted, rejected, or superseded, with the date and who chaired the decision. If superseded, link the RFC that replaces this one.