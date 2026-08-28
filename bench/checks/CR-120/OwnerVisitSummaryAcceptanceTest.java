package org.springframework.samples.petclinic.api.application;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

import mockwebserver3.MockResponse;
import mockwebserver3.MockWebServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.webflux.test.autoconfigure.WebFluxTest;
import org.springframework.cloud.circuitbreaker.resilience4j.ReactiveResilience4JAutoConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.samples.petclinic.api.boundary.web.CircuitBreakerConfiguration;
import org.springframework.samples.petclinic.api.dto.OwnerDetails;
import org.springframework.samples.petclinic.api.dto.PetDetails;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.reactive.server.WebTestClient;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

/**
 * Acceptance check for CR-120, gateway side: the summary is composed from the two
 * services, and the gateway says so when it cannot compose it.
 *
 * The visits client is the real one, pointed at a stub server, so the check reads the
 * traffic the gateway actually sends rather than a mock of a method it might not have.
 * The whole web layer is loaded rather than one named class, so it does not matter
 * which class the route is added to.
 */
@WebFluxTest
@Import({ReactiveResilience4JAutoConfiguration.class, CircuitBreakerConfiguration.class})
class OwnerVisitSummaryAcceptanceTest {

    @TestConfiguration
    static class RealVisitsClient {

        @Bean
        VisitsServiceClient visitsServiceClient() {
            return new VisitsServiceClient(WebClient.builder());
        }
    }

    @MockitoBean
    private CustomersServiceClient customersServiceClient;

    @Autowired
    private VisitsServiceClient visitsServiceClient;

    @Autowired
    private WebTestClient client;

    private MockWebServer server;

    @BeforeEach
    void setUp() {
        server = new MockWebServer();
        visitsServiceClient.setHostname(server.url("/").toString());
    }

    @AfterEach
    void shutdown() throws IOException {
        server.close();
    }

    private void givenTheOwner(int ownerId, List<PetDetails> pets) {
        OwnerDetails owner = OwnerDetails.OwnerDetailsBuilder.anOwnerDetails()
            .id(ownerId)
            .firstName("George")
            .lastName("Franklin")
            .pets(pets)
            .build();
        Mockito.when(customersServiceClient.getOwner(ownerId)).thenReturn(Mono.just(owner));
    }

    private PetDetails aPet(int id, String name) {
        return PetDetails.PetDetailsBuilder.aPetDetails()
            .id(id)
            .name(name)
            .visits(new ArrayList<>())
            .build();
    }

    private void enqueueSummary(String body) {
        server.enqueue(new MockResponse.Builder()
            .addHeader("Content-Type", "application/json")
            .body(body)
            .build());
    }

    @Test
    void shouldComposeTheSummaryForAnOwnersPets() {
        givenTheOwner(1, List.of(aPet(7, "Leo")));
        enqueueSummary("{\"summaries\":[{\"petId\":7,\"visitCount\":2,"
            + "\"lastVisitDate\":\"2013-01-04\"}]}");

        client.get()
            .uri("/api/gateway/owners/1/visit-summary")
            .exchange()
            .expectStatus().isOk()
            .expectBody()
            .jsonPath("$.ownerId").isEqualTo(1)
            .jsonPath("$.pets.length()").isEqualTo(1)
            .jsonPath("$.pets[0].petId").isEqualTo(7)
            .jsonPath("$.pets[0].name").isEqualTo("Leo")
            .jsonPath("$.pets[0].visitCount").isEqualTo(2)
            .jsonPath("$.pets[0].lastVisitDate").isEqualTo("2013-01-04");
    }

    @Test
    void shouldCarryAnEntryForEveryPetIncludingOnesWithNothing() {
        givenTheOwner(1, List.of(aPet(7, "Leo"), aPet(9, "Basil")));
        enqueueSummary("{\"summaries\":[{\"petId\":7,\"visitCount\":2,"
            + "\"lastVisitDate\":\"2013-01-04\"},"
            + "{\"petId\":9,\"visitCount\":0,\"lastVisitDate\":null}]}");

        client.get()
            .uri("/api/gateway/owners/1/visit-summary")
            .exchange()
            .expectStatus().isOk()
            .expectBody()
            .jsonPath("$.pets.length()").isEqualTo(2)
            .jsonPath("$.pets[1].petId").isEqualTo(9)
            .jsonPath("$.pets[1].name").isEqualTo("Basil")
            .jsonPath("$.pets[1].visitCount").isEqualTo(0);
    }

    @Test
    void shouldAnswerAnOwnerWithNoPetsWithNoEntries() {
        givenTheOwner(2, new ArrayList<>());

        client.get()
            .uri("/api/gateway/owners/2/visit-summary")
            .exchange()
            .expectStatus().isOk()
            .expectBody()
            .jsonPath("$.ownerId").isEqualTo(2)
            .jsonPath("$.pets").isEmpty();
    }

    @Test
    void shouldRefuseRatherThanReportZeroWhenTheVisitsServiceIsGone() {
        givenTheOwner(1, List.of(aPet(7, "Leo")));
        server.enqueue(new MockResponse.Builder().code(500).build());

        client.get()
            .uri("/api/gateway/owners/1/visit-summary")
            .exchange()
            .expectStatus().isEqualTo(503);
    }
}
