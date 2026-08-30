package org.springframework.samples.petclinic.api.application;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.IntStream;

import mockwebserver3.MockResponse;
import mockwebserver3.MockWebServer;
import mockwebserver3.RecordedRequest;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.samples.petclinic.api.dto.VisitDetails;
import org.springframework.samples.petclinic.api.dto.Visits;
import org.springframework.web.reactive.function.client.WebClient;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Acceptance check for CR-116: a lookup over many pets is split, covers each pet once,
 * and comes back as one answer; a small lookup is still a single request.
 *
 * The identifiers are read back off the requests the client actually made, however it
 * chose to carry them --- one parameter holding a list, or a parameter per pet.
 *
 * Passability: Partition the identifiers in the client and merge the answers. The
 * fixture points the real client at a stub server and reads the requests it actually
 * made, so no method the agent adds needs naming and the merge is observable in the
 * returned object.
 * Confirmed empirically: 12 of 12 cells passed it in the full run.
 */
class VisitsBatchingAcceptanceTest {

    private static final int LIMIT = 100;

    private VisitsServiceClient visitsServiceClient;

    private MockWebServer server;

    @BeforeEach
    void setUp() {
        server = new MockWebServer();
        visitsServiceClient = new VisitsServiceClient(WebClient.builder());
        visitsServiceClient.setHostname(server.url("/").toString());
    }

    @AfterEach
    void shutdown() throws IOException {
        this.server.close();
    }

    private void enqueueVisitFor(int petId) {
        server.enqueue(new MockResponse.Builder()
            .addHeader("Content-Type", "application/json")
            .body("{\"items\":[{\"id\":" + petId + ",\"date\":\"2018-11-15\","
                + "\"description\":\"visit for " + petId + "\",\"petId\":" + petId + "}]}")
            .build());
    }

    private List<Integer> petIds(int count) {
        return IntStream.rangeClosed(1, count).boxed().toList();
    }

    /** Every pet identifier carried by one request, however it was carried. */
    private List<Integer> identifiersOf(RecordedRequest request) {
        List<Integer> identifiers = new ArrayList<>();
        for (String value : request.getRequestUrl().queryParameterValues("petId")) {
            if (value == null || value.isBlank()) {
                continue;
            }
            for (String part : value.split(",")) {
                identifiers.add(Integer.valueOf(part.trim()));
            }
        }
        return identifiers;
    }

    private List<List<Integer>> requestsMade(int count) throws InterruptedException {
        List<List<Integer>> made = new ArrayList<>();
        for (int index = 0; index < count; index++) {
            made.add(identifiersOf(server.takeRequest()));
        }
        return made;
    }

    @Test
    void shouldSplitALargeLookupAndCoverEveryPetOnce() throws Exception {
        List<Integer> asked = petIds(250);
        for (int index = 0; index < 3; index++) {
            enqueueVisitFor(index + 1);
        }

        Visits visits = visitsServiceClient.getVisitsForPets(asked).block();

        assertThat(server.getRequestCount())
            .as("250 pets at a hundred a time")
            .isEqualTo(3);

        List<List<Integer>> made = requestsMade(3);
        for (List<Integer> request : made) {
            assertThat(request).as("no request over the limit").hasSizeLessThanOrEqualTo(LIMIT);
        }
        List<Integer> everything = made.stream().flatMap(List::stream).toList();
        assertThat(everything)
            .as("every pet asked about exactly once")
            .hasSize(asked.size())
            .containsExactlyInAnyOrderElementsOf(asked);

        assertThat(visits).isNotNull();
        assertThat(visits.items().stream().map(VisitDetails::petId).toList())
            .as("every answer merged")
            .containsExactlyInAnyOrder(1, 2, 3);
    }

    @Test
    void shouldStillMakeOneRequestForALookupAtTheLimit() throws Exception {
        enqueueVisitFor(1);

        visitsServiceClient.getVisitsForPets(petIds(LIMIT)).block();

        assertThat(server.getRequestCount()).isEqualTo(1);
        assertThat(requestsMade(1).get(0)).hasSize(LIMIT);
    }

    @Test
    void shouldStillMakeOneRequestForASinglePet() throws Exception {
        enqueueVisitFor(1);

        Visits visits = visitsServiceClient.getVisitsForPets(List.of(1)).block();

        assertThat(server.getRequestCount()).isEqualTo(1);
        assertThat(requestsMade(1).get(0)).containsExactly(1);
        assertThat(visits).isNotNull();
        assertThat(visits.items()).hasSize(1);
        assertThat(visits.items().get(0).description()).isEqualTo("visit for 1");
    }
}
