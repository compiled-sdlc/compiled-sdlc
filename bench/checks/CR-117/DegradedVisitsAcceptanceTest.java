package org.springframework.samples.petclinic.api.boundary.web;

import java.net.ConnectException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webflux.test.autoconfigure.WebFluxTest;
import org.springframework.cloud.circuitbreaker.resilience4j.ReactiveResilience4JAutoConfiguration;
import org.springframework.context.annotation.Import;
import org.springframework.samples.petclinic.api.application.CustomersServiceClient;
import org.springframework.samples.petclinic.api.application.VisitsServiceClient;
import org.springframework.samples.petclinic.api.dto.OwnerDetails;
import org.springframework.samples.petclinic.api.dto.PetDetails;
import org.springframework.samples.petclinic.api.dto.VisitDetails;
import org.springframework.samples.petclinic.api.dto.Visits;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.reactive.server.WebTestClient;
import reactor.core.publisher.Mono;

/**
 * Acceptance check for CR-117: the marker follows what actually happened to the visits,
 * and the body is untouched either way.
 */
@WebFluxTest(controllers = ApiGatewayController.class)
@Import({ReactiveResilience4JAutoConfiguration.class, CircuitBreakerConfiguration.class})
class DegradedVisitsAcceptanceTest {

    private static final String MARKER = "X-Visits-Degraded";

    @MockitoBean
    private CustomersServiceClient customersServiceClient;

    @MockitoBean
    private VisitsServiceClient visitsServiceClient;

    @Autowired
    private WebTestClient client;

    private PetDetails aPet() {
        return PetDetails.PetDetailsBuilder.aPetDetails()
            .id(20)
            .name("Garfield")
            .visits(new ArrayList<>())
            .build();
    }

    private void givenAnOwnerWithOnePet(PetDetails pet) {
        OwnerDetails owner = OwnerDetails.OwnerDetailsBuilder.anOwnerDetails()
            .id(1)
            .firstName("George")
            .lastName("Franklin")
            .pets(List.of(pet))
            .build();
        Mockito.when(customersServiceClient.getOwner(1)).thenReturn(Mono.just(owner));
    }

    @Test
    void shouldMarkTheAnswerDegradedWhenTheVisitsCouldNotBeFetched() {
        PetDetails cat = aPet();
        givenAnOwnerWithOnePet(cat);
        Mockito.when(visitsServiceClient.getVisitsForPets(Collections.singletonList(cat.id())))
            .thenReturn(Mono.error(new ConnectException("the visits service is down")));

        client.get()
            .uri("/api/gateway/owners/1")
            .exchange()
            .expectStatus().isOk()
            .expectHeader().valueEquals(MARKER, "true")
            .expectBody()
            .jsonPath("$.firstName").isEqualTo("George")
            .jsonPath("$.pets[0].name").isEqualTo("Garfield")
            .jsonPath("$.pets[0].visits").isEmpty();
    }

    @Test
    void shouldMarkTheAnswerHealthyWhenTheVisitsAreTheRealOnes() {
        PetDetails cat = aPet();
        givenAnOwnerWithOnePet(cat);
        VisitDetails visit = new VisitDetails(300, cat.id(), null, "First visit");
        Mockito.when(visitsServiceClient.getVisitsForPets(Collections.singletonList(cat.id())))
            .thenReturn(Mono.just(new Visits(List.of(visit))));

        client.get()
            .uri("/api/gateway/owners/1")
            .exchange()
            .expectStatus().isOk()
            .expectHeader().valueEquals(MARKER, "false")
            .expectBody()
            .jsonPath("$.firstName").isEqualTo("George")
            .jsonPath("$.pets[0].name").isEqualTo("Garfield")
            .jsonPath("$.pets[0].visits[0].description").isEqualTo("First visit");
    }

    @Test
    void shouldMarkAnOwnerWithNoPetsHealthyWhenNothingFailed() {
        OwnerDetails owner = OwnerDetails.OwnerDetailsBuilder.anOwnerDetails()
            .id(2)
            .firstName("Betty")
            .lastName("Davis")
            .pets(new ArrayList<>())
            .build();
        Mockito.when(customersServiceClient.getOwner(2)).thenReturn(Mono.just(owner));
        Mockito.when(visitsServiceClient.getVisitsForPets(Collections.emptyList()))
            .thenReturn(Mono.just(new Visits(List.of())));

        client.get()
            .uri("/api/gateway/owners/2")
            .exchange()
            .expectStatus().isOk()
            .expectHeader().valueEquals(MARKER, "false")
            .expectBody()
            .jsonPath("$.firstName").isEqualTo("Betty");
    }
}
